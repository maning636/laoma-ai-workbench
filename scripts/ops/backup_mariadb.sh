#!/usr/bin/env bash
# =============================================================================
# backup_mariadb.sh
#
# Purpose : 对生产库 prism_cloud (MariaDB 10.11.x @ 127.0.0.1) 做全量逻辑备份,
#           压缩后落到 /opt/prism-fusion/backups/,并按 mtime 保留最近 7 天。
#
# Source  : 数据库账号与密码从 /opt/prism-fusion/.db_credentials/.env 中读取,
#           该文件由 deploy/deploy.sh 校验,内容为
#               CLOUD_DB_URL=mysql+pymysql://prism:<password>@127.0.0.1:3306/prism_cloud
#           脚本运行时**不会**把密码写到任何持久文件,也不会打印到 stdout/stderr。
#
# Output  : /opt/prism-fusion/backups/prism_cloud_YYYY-MM-DD_HHMMSS.sql.gz
#
# Retention: 默认删除 mtime > 7 天的旧备份; 可用 BACKUP_KEEP_DAYS 覆盖。
#
# Safety :  - set -euo pipefail, 任一步骤失败立即以非 0 退出。
#          - 凭据走 --defaults-extra-file, 不会出现在 `ps` 参数里。
#          - 密码通过 python3 对 URL 做 unquote, 兼容含 @ : / ? # 等特殊字符的密码。
#          - 临时凭据文件放在 /dev/shm (RAM),权限 0600,退出即删。
#
# Run   : sudo bash /opt/prism-fusion/app/scripts/ops/backup_mariadb.sh
# Cron  : 0 2 * * *  root /usr/bin/flock -n /tmp/backup_prism.lock \
#                  /usr/bin/bash /opt/prism-fusion/app/scripts/ops/backup_mariadb.sh \
#                  >> /var/log/backup_prism.log 2>&1
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

# ------------------------------------------------------------------ 可配置项 --
BASE_DIR="${BASE_DIR:-/opt/prism-fusion}"
CRED_DIR="${CRED_DIR:-${BASE_DIR}/.db_credentials}"
BACKUP_DIR="${BACKUP_DIR:-${BASE_DIR}/backups}"
DB_NAME="${DB_NAME:-prism_cloud}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-7}"
TMP_PWD_FILE="${TMP_PWD_FILE:-/dev/shm/.backup_prism_$$_pw}"

# ---------------------------------------------------------- 日志 / 依赖检查 --
log()  { printf '[backup %s] %s\n' "$(date +%Y-%m-%d_%H%M%S)" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }

for cmd in mysqldump gzip python3 find; do
  command -v "${cmd}" >/dev/null 2>&1 || fail "missing dependency: ${cmd}"
done

[[ -d "${CRED_DIR}" ]] || fail "credentials dir not found: ${CRED_DIR}"
[[ -f "${CRED_DIR}/.env" ]] || fail "credentials file not found: ${CRED_DIR}/.env"
[[ -r "${CRED_DIR}/.env" ]] || fail "credentials file not readable by current user: ${CRED_DIR}/.env"

# 载入凭据文件（deploy.sh 生成的 KEY=value 格式，权限 600，含 CLOUD_DB_URL=...）。
# 早期版本只检查文件存在却**从不载入**，导致 $CLOUD_DB_URL 未绑定变量，
# 脚本在 set -u 下直接报 "CLOUD_DB_URL: unbound variable" 而退出。
# 这里不用 `set -a`：DB_PASSWORD 等只需要作为 shell 变量，
# 导出到环境反而扩大暴露面（子进程 environ 可见）。
if [[ -z "${CLOUD_DB_URL:-}" ]]; then
  # shellcheck disable=SC1091
  . "${CRED_DIR}/.env"
fi
[[ -n "${CLOUD_DB_URL:-}" ]] || fail "CLOUD_DB_URL not found in ${CRED_DIR}/.env"
# 凭据文件里若带 DB_NAME 则以它为准；为空则回落到默认库名。
DB_NAME="${DB_NAME:-prism_cloud}"

mkdir -p "${BACKUP_DIR}"
chmod 700 "${BACKUP_DIR}" 2>/dev/null || true

# ------------------------------------------- 从 CLOUD_DB_URL 中解析账号与密码 --
# 密码**不**进入 stdout/stderr,也不写入任何非 tmpfs 的路径。
parse_credential() {
  # URL 经**环境变量**传给 python，而不是 argv —— argv 会出现在 `ps` 输出里，
  # 那等于把数据库口令暴露给同机任意用户。环境变量只在 /proc/<pid>/environ
  # 中可见（root 权限），符合本脚本"密码不出现在 ps 参数里"的设计目标。
  CLOUD_DB_URL="${CLOUD_DB_URL}" python3 - "${DB_NAME}" <<'PY'
import os, sys
from urllib.parse import urlparse, unquote

url = os.environ.get("CLOUD_DB_URL") or ""
expected_db = sys.argv[1]

if not url:
    sys.exit("[backup] CLOUD_DB_URL is empty (not loaded from the credentials file?)")
if not url.startswith("mysql"):
    sys.exit("[backup] CLOUD_DB_URL must start with 'mysql...' (got unexpected scheme)")

# 屏蔽 SQLAlchemy 的 driver 前缀,例如 mysql+pymysql:// -> mysql://
scheme, sep, rest = url.partition("://")
if not sep:
    sys.exit("[backup] malformed CLOUD_DB_URL")
scheme = scheme.split("+", 1)[0]
url = f"{scheme}://{rest}"

p = urlparse(url)
if not p.hostname or not p.username:
    sys.exit("[backup] CLOUD_DB_URL must contain user@host")
if not p.password:
    sys.exit("[backup] CLOUD_DB_URL must contain a password")
if not p.path or not p.path.startswith("/"):
    sys.exit("[backup] CLOUD_DB_URL must contain a database name after the host")

db_in_url = unquote(p.path.lstrip("/").split("/", 1)[0])
if db_in_url != expected_db:
    sys.exit(f"[backup] DB_NAME mismatch: expected {expected_db!r}, URL says {db_in_url!r}")

# 打印顺序: host, port, password, user —— 便于 shell 用 read 一次性吃下
# 顺序故意把 password 放在中间,方便 shell 用 _pw 前缀标记其为敏感字段
print(p.hostname or "127.0.0.1")
print(p.port or 3306)
print(unquote(p.password))
print(unquote(p.username))
PY
}

# parse_credential 输出 4 行(host / port / password / user)。
# 注意:不能用 `read -r A B C D <<<"$creds"` —— here-string 只会喂给 read 一行,
# 后面三个变量会全为空,导致 "empty DB port parsed from CLOUD_DB_URL"。
# 这里用 mapfile 按行读满 4 行再按下标赋值。
mapfile -t CRED_LINES < <(parse_credential)
[[ "${#CRED_LINES[@]}" -eq 4 ]] || fail "expected 4 credential lines from CLOUD_DB_URL, got ${#CRED_LINES[@]}"
DB_HOST="${CRED_LINES[0]}"
DB_PORT="${CRED_LINES[1]}"
DB_PASSWORD="${CRED_LINES[2]}"
DB_USER="${CRED_LINES[3]}"

[[ -n "${DB_HOST}"      ]] || fail "empty DB host parsed from CLOUD_DB_URL"
[[ -n "${DB_PORT}"      ]] || fail "empty DB port parsed from CLOUD_DB_URL"
[[ -n "${DB_PASSWORD}"  ]] || fail "empty DB password parsed from CLOUD_DB_URL"
[[ -n "${DB_USER}"      ]] || fail "empty DB user parsed from CLOUD_DB_URL"

# --------------------------------------------- 写临时 .my.cnf (RAM tmpfs, 0600) --
touch "${TMP_PWD_FILE}"
chmod 600 "${TMP_PWD_FILE}"
trap 'rm -f "${TMP_PWD_FILE}"' EXIT

cat > "${TMP_PWD_FILE}" <<EOF
[client]
user=${DB_USER}
host=${DB_HOST}
port=${DB_PORT}
password=${DB_PASSWORD}
EOF

# --------------------------------------------------------------- 生成备份文件 --
STAMP="$(date +%Y-%m-%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${STAMP}.sql.gz"

log "starting backup: db=${DB_NAME}@${DB_HOST}:${DB_PORT} user=${DB_USER} -> ${BACKUP_FILE}"

# --single-transaction : 对 InnoDB 做一致性快照, 不锁表
# --routines           : 附带存储过程 / 函数 / 触发器 / 事件
# --databases          : dump 里会写 CREATE DATABASE / USE, 便于直接恢复
# --defaults-file      : **只**读这个文件, 跳过 /root/.my.cnf 等所有默认文件。
#                        必须放在命令行最前面(mysql 客户端要求选项文件类选项居首)。
#                        早期版本用 `--no-defaults --defaults-extra-file=...`,
#                        但这两个选项在 mysql 客户端里互斥 —— --no-defaults 禁止
#                        再使用 --defaults-extra-file, 会报
#                        "unknown variable 'defaults-extra-file=...'"。
if ! mysqldump \
       --defaults-file="${TMP_PWD_FILE}" \
       --single-transaction \
       --routines \
       --triggers \
       --events \
       --databases "${DB_NAME}" \
     | gzip -9 > "${BACKUP_FILE}"; then
  rm -f "${BACKUP_FILE}"
  fail "mysqldump failed; partial file removed"
fi

# 简单健全性校验: gzip 可解压 且 输出大小合理
gzip -t "${BACKUP_FILE}"
SIZE_BYTES="$(stat -c %s "${BACKUP_FILE}")"
[[ "${SIZE_BYTES}" -gt 1024 ]] || fail "backup file suspiciously small: ${SIZE_BYTES} bytes"

log "backup done: ${BACKUP_FILE} ($(numfmt --to=iec "${SIZE_BYTES}" 2>/dev/null || echo "${SIZE_BYTES}B"))"

# --------------------------------------------------------------- 轮转: 保留 N 天 --
log "rotating backups older than ${KEEP_DAYS} days under ${BACKUP_DIR}"
find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${DB_NAME}_*.sql.gz" -mtime +"${KEEP_DAYS}" -delete

REMAINING="$(find "${BACKUP_DIR}" -maxdepth 1 -type f -name "${DB_NAME}_*.sql.gz" | wc -l | tr -d ' ')"
log "retention ok: ${REMAINING} backup file(s) kept under ${BACKUP_DIR}"
