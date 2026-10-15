#!/usr/bin/env bash
# =============================================================================
# Prism-Fusion Cloud Service — 服务器端部署脚本(幂等)
# =============================================================================
# 目标服务器:OpenCloudOS 9.6(RHEL 系)
#   4 核 / 内存 3.6G(可用约 2.8G) / 磁盘剩 33G
#   nginx 1.29.8(只对外监听 80/443)
#   MariaDB 10.11.18(只监听 127.0.0.1:3306)
#   内部端口 8090 = payskill-server,8787 = python3(与本脚本无关,只读)
#   本服务:cloud_service → 127.0.0.1:8091
#
# 目录布局(约定,与 systemd unit / nginx 片段一致):
#   /opt/prism-fusion/repo.git       ← 裸仓库(git push 落点)
#   /opt/prism-fusion/app            ← 工作树(git clone / pull 结果)
#   /opt/prism-fusion/venv           ← Python 虚拟环境
#   /opt/prism-fusion/.db_credentials ← 目录 700 / 文件 600,含 CLOUD_DB_URL=...
#   /opt/prism-fusion/.env.cloud     ← 应用环境变量(JWT / LLM key / admin token 等)
#
# 使用方式:
#   sudo bash /opt/prism-fusion/app/deploy/deploy.sh
#   # 或者首次 clone 后从 app 目录跑:
#   cd /opt/prism-fusion/app && sudo bash deploy/deploy.sh
#
# -----------------------------------------------------------------------------
# **本脚本不做的事(重要,请勿扩展)**:
#   ✗ 不修改 /etc/nginx/conf.d/fde.conf —— 那是 Pay Skill 项目的 server 块。
#   ✗ 不主动 systemctl reload/restart nginx —— 只做 nginx -t 校验,
#     reload 由人工确认;nginx 配置首次落位需要手工 cp。
#   ✗ 不自动创建 .env.cloud 或 .db_credentials —— 缺任一个立即报错退出。
#     生产凭据必须由运维显式提供,脚本不生成任何 secret。
#   ✗ 不打开/关闭防火墙(不在 firewalld / 云安全组里做任何改动)。
#   ✗ 不修改 MariaDB 现有账号密码,只在 init_db 里对已存在的 prism_cloud 库
#     做 Base.metadata.create_all(幂等建表)。
#   ✗ 不装仓库根 requirements.txt —— 只装 cloud_service 需要的最小集合。
#   ✗ 不装 node / npm / next,前端产物在本地构建后再上传,不在这台机器上 build。
#   ✗ 不覆盖已存在的 systemd unit —— 用 cp + daemon-reload,但保留备份。
#   ✗ 不删除 /opt/prism-fusion 下任何文件。
# -----------------------------------------------------------------------------

set -euo pipefail

# ── 常量 ──────────────────────────────────────────────────────────────────
BASE_DIR="/opt/prism-fusion"
REPO_GIT="${BASE_DIR}/repo.git"
APP_DIR="${BASE_DIR}/app"
VENV_DIR="${BASE_DIR}/venv"
DB_CRED_DIR="${BASE_DIR}/.db_credentials"
DB_CRED_FILE="${BASE_DIR}/.db_credentials/.env"     # 若你实际文件名为其它,请改这里
ENV_CLOUD="${BASE_DIR}/.env.cloud"
SYSTEMD_UNIT_SRC="deploy/prism-cloud.service"
SYSTEMD_UNIT_DST="/etc/systemd/system/prism-cloud.service"
NGINX_CONF_SRC="deploy/nginx-prism-cloud.conf"
NGINX_CONF_DST="/etc/nginx/conf.d/prism-cloud.conf"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="8091"
HEALTH_URL="http://${BACKEND_HOST}:${BACKEND_PORT}/health"
LOG_PREFIX="[prism-cloud]"

# cloud_service 最小运行时依赖(以源码 import 为准,不含 dev / test 依赖):
#   - fastapi                cloud_service/main.py, router/*.py
#   - uvicorn[standard]      生产 ASGI server(Type=notify 需要 uvloop + httptools)
#   - sqlalchemy             cloud_service/db.py + models
#   - pymysql                SQLAlchemy 驱动 mysql+pymysql://... (MariaDB)
#   - pyjwt                  cloud_service/auth/security.py (`import jwt`)
#   - bcrypt                 cloud_service/auth/security.py
#   - openai                 cloud_service/llm_proxy/llm_client.py
#   - httpx                  部分 payment adapter / openai 传递依赖(显式列出防 pip 解析偏差)
#   - loguru                 llm_proxy/router.py 里的可选日志
#   - pydantic               schemas.py 直接 import(FastAPI 会传递依赖,但显式更稳)
PIP_PACKAGES=(
    "fastapi>=0.110,<1"
    "uvicorn[standard]>=0.30,<1"
    "sqlalchemy>=2.0,<3"
    "pymysql>=1.1,<2"
    "cryptography"                # pymysql + sha256_password 认证需要
    "pyjwt>=2.8,<3"
    "bcrypt>=4.0,<5"
    "openai>=1.30,<2"
    "httpx>=0.27,<1"
    "loguru>=0.7,<1"
    "pydantic>=2.0,<3"
    "python-multipart"            # FastAPI File/Form 解析(隐式依赖)
    "python-dotenv"               # 若后续要用 dotenv 加载 .env.cloud
)

# ── 日志辅助 ──────────────────────────────────────────────────────────────
log_step() { printf '\n%s ▶ %s\n' "${LOG_PREFIX}" "$1"; }
log_ok()   { printf '%s ✓ %s\n' "${LOG_PREFIX}" "$1"; }
log_warn() { printf '%s ⚠ %s\n' "${LOG_PREFIX}" "$1" >&2; }
log_err()  { printf '%s ✗ %s\n' "${LOG_PREFIX}" "$1" >&2; }
die()      { log_err "$*"; exit 1; }

require_root() {
    [[ "${EUID}" -eq 0 ]] || die "请以 root 运行本脚本(推荐: sudo bash $0)"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 0:前置检查
# ═════════════════════════════════════════════════════════════════════════
precheck() {
    log_step "Step 0/9 · 前置检查"

    require_root

    # 0.1 包管理器(dnf / yum,禁止出现 apt)
    if ! command -v dnf >/dev/null 2>&1 && ! command -v yum >/dev/null 2>&1; then
        die "未找到 dnf 或 yum,本脚本仅支持 RHEL 系(OpenCloudOS / Rocky / Alma)。"
    fi
    PKG_MGR="dnf"
    command -v dnf >/dev/null 2>&1 || PKG_MGR="yum"
    log_ok "包管理器:${PKG_MGR}"

    # 0.2 Python 3 版本
    if ! command -v python3 >/dev/null 2>&1; then
        die "未找到 python3,请 ${PKG_MGR} install -y python3"
    fi
    PY_VERSION="$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
    log_ok "Python 版本:${PY_VERSION}"
    python3 - <<'PY' || die "Python 版本过低,cloud_service 需要 >= 3.10"
import sys
assert sys.version_info >= (3, 10), sys.version
PY

    # 0.3 目标目录
    [[ -d "${BASE_DIR}" ]] || die "缺失 ${BASE_DIR},请先创建目录布局"
    log_ok "BASE_DIR 存在:${BASE_DIR}"

    # 0.4 MariaDB active(只检查状态,不修改)
    if systemctl list-unit-files | awk '{print $1}' | grep -qE '^mariadb\.service$|^mariadb-server\.service$'; then
        if ! systemctl is-active --quiet mariadb.service 2>/dev/null \
           && ! systemctl is-active --quiet mariadb-server.service 2>/dev/null; then
            log_warn "MariaDB service 存在但未 active —— 请先 systemctl start mariadb"
            # 不直接 die,因为 init_db 也可能用 sqlite fallback;
            # 但 CLOUD_DB_URL 走 mysql+pymysql 时会连不上。这里给出 warning,让后面 init_db 时报错更精准。
        else
            log_ok "MariaDB 状态:active"
        fi
    else
        log_warn "未发现 mariadb/mariadb-server systemd unit,请人工确认数据库服务"
    fi

    # 0.5 curl(健康检查需要)
    command -v curl >/dev/null 2>&1 || ${PKG_MGR} install -y curl >/dev/null

    # 0.6 git(下一步要用)
    if ! command -v git >/dev/null 2>&1; then
        log_step "Step 1/9 · 安装 git + python3-pip(缺失才装)"
        ${PKG_MGR} install -y git
    else
        log_step "Step 1/9 · git 已安装,跳过"
    fi
    if ! command -v pip3 >/dev/null 2>&1 && ! "${VENV_DIR}/bin/pip" 2>/dev/null --version >/dev/null; then
        log_step "Step 1/9 · 安装 python3-pip(缺失才装)"
        ${PKG_MGR} install -y python3-pip
    else
        log_step "Step 1/9 · python3-pip 已可用,跳过"
    fi
    log_ok "Step 1/9 完成"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 2:venv 创建/复用 + 安装 cloud_service 依赖
# ═════════════════════════════════════════════════════════════════════════
setup_venv() {
    log_step "Step 2/9 · 准备 Python 虚拟环境 ${VENV_DIR}"

    if [[ -x "${VENV_DIR}/bin/python" ]]; then
        log_ok "venv 已存在,复用"
    else
        python3 -m venv "${VENV_DIR}"
        log_ok "venv 已创建:${VENV_DIR}"
    fi

    # 升级 pip / setuptools / wheel,避免老 pip 解析依赖出错
    "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel >/dev/null

    log_step "Step 2/9 · 安装 cloud_service 依赖(最小集合)"
    # shellcheck disable=SC2068
    "${VENV_DIR}/bin/pip" install --upgrade "${PIP_PACKAGES[@]}"
    log_ok "依赖安装完成"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 3:拉取代码
# ═════════════════════════════════════════════════════════════════════════
sync_code() {
    log_step "Step 3/9 · 同步代码到 ${APP_DIR}"

    if [[ -d "${APP_DIR}/.git" ]]; then
        # 已有工作树 → pull(要求本地没有未提交改动;有则中止)
        if ! git -C "${APP_DIR}" diff --quiet || ! git -C "${APP_DIR}" diff --cached --quiet; then
            die "${APP_DIR} 存在本地未提交改动,拒绝 pull。请先手工处理。"
        fi
        git -C "${APP_DIR}" fetch --all --tags --prune
        git -C "${APP_DIR}" pull --ff-only
        log_ok "pull 完成:${APP_DIR}"
    elif [[ -d "${REPO_GIT}" && "${REPO_GIT}" != "${APP_DIR}" ]]; then
        # 有裸仓库 → clone 到 app
        if [[ -e "${APP_DIR}" ]]; then
            die "${APP_DIR} 已存在但不是 git 工作树,且不是 .git 目录,拒绝自动删除。"
        fi
        git clone "${REPO_GIT}" "${APP_DIR}"
        log_ok "clone 完成:${REPO_GIT} → ${APP_DIR}"
    else
        die "未找到 ${REPO_GIT} 或 ${APP_DIR}/.git。方案 B 要求先在服务器上: git init --bare ${REPO_GIT} 并从本地 push 一次。"
    fi

    # 校验 deploy/ 目录存在
    [[ -f "${APP_DIR}/${SYSTEMD_UNIT_SRC}" ]] \
        || die "缺失 ${APP_DIR}/${SYSTEMD_UNIT_SRC}"
    [[ -f "${APP_DIR}/${NGINX_CONF_SRC}" ]] \
        || die "缺失 ${APP_DIR}/${NGINX_CONF_SRC}"
    log_ok "deploy/ 目录已就位"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 4:校验凭据文件
# ═════════════════════════════════════════════════════════════════════════
check_credentials() {
    log_step "Step 4/9 · 校验凭据文件"

    # .db_credentials 目录 + 内含 CLOUD_DB_URL
    if [[ ! -d "${DB_CRED_DIR}" ]]; then
        die "缺失 ${DB_CRED_DIR}(目录权限应为 700,内含 CLOUD_DB_URL=mysql+pymysql://...)"
    fi
    # 兼容两种命名:目录本身叫 .db_credentials,里面可能有一个 .env / .db_credentials
    local cred_file=""
    if [[ -f "${DB_CRED_DIR}/.env" ]]; then
        cred_file="${DB_CRED_DIR}/.env"
    elif [[ -f "${DB_CRED_DIR}/.db_credentials" ]]; then
        cred_file="${DB_CRED_DIR}/.db_credentials"
    elif [[ -f "${DB_CRED_DIR}" && ! -d "${DB_CRED_DIR}" ]]; then
        cred_file="${DB_CRED_DIR}"
    else
        die "在 ${DB_CRED_DIR} 下未找到 .env 或 .db_credentials 文件。"
    fi
    chmod 700 "${DB_CRED_DIR}" 2>/dev/null || true
    chmod 600 "${cred_file}" 2>/dev/null || true

    if ! grep -q '^CLOUD_DB_URL=' "${cred_file}"; then
        die "在 ${cred_file} 中未找到 CLOUD_DB_URL= 行"
    fi
    log_ok "数据库凭据文件:${cred_file}"

    # .env.cloud 必须存在
    if [[ ! -f "${ENV_CLOUD}" ]]; then
        die "缺失 ${ENV_CLOUD}。请手工创建,包含 JWT / LLM / admin token 等变量(参见 deploy/README.md 变量清单)。"
    fi
    chmod 600 "${ENV_CLOUD}" 2>/dev/null || true
    log_ok "应用环境变量文件:${ENV_CLOUD}"

    # 关键:确保 CLOUD_DB_URL 也出现在 .env.cloud(systemd EnvironmentFile 只读 .env.cloud)
    # 如果 .env.cloud 里没写 CLOUD_DB_URL,那就 source .db_credentials 追加
    if ! grep -q '^CLOUD_DB_URL=' "${ENV_CLOUD}"; then
        log_warn ".env.cloud 中未含 CLOUD_DB_URL —— 自动从 ${cred_file} 追加一条到 .env.cloud(仅追加,不覆盖)"
        # 提取 db url 那一行,追加到 .env.cloud(带一行注释说明来源)
        {
            echo "# ── 从 ${cred_file} 注入 ──"
            grep '^CLOUD_DB_URL=' "${cred_file}"
        } >> "${ENV_CLOUD}"
    fi
    log_ok "CLOUD_DB_URL 已就绪于 .env.cloud"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 5:初始化数据库表
# ═════════════════════════════════════════════════════════════════════════
init_database() {
    log_step "Step 5/9 · 初始化数据库表(idempotent)"
    (
        cd "${APP_DIR}"
        # 用 set -a 把 .env.cloud 里的变量导出,给 Python 子进程读
        set -a
        # shellcheck disable=SC1090
        source "${ENV_CLOUD}"
        set +a
        "${VENV_DIR}/bin/python" -c \
            "from cloud_service.db import init_db; init_db(); print('init_db OK')"
    )
    log_ok "init_db 完成"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 6:安装/更新 systemd unit
# ═════════════════════════════════════════════════════════════════════════
install_systemd_unit() {
    log_step "Step 6/9 · 安装 systemd unit → ${SYSTEMD_UNIT_DST}"

    # 若目标已存在,先备份(带时间戳,便于回滚)
    if [[ -f "${SYSTEMD_UNIT_DST}" ]]; then
        local backup="${SYSTEMD_UNIT_DST}.bak.$(date +%Y%m%d%H%M%S)"
        cp -a "${SYSTEMD_UNIT_DST}" "${backup}"
        log_ok "已备份旧 unit → ${backup}"
    fi

    cp "${APP_DIR}/${SYSTEMD_UNIT_SRC}" "${SYSTEMD_UNIT_DST}"
    chmod 644 "${SYSTEMD_UNIT_DST}"
    systemctl daemon-reload

    # enable --now 会:
    #   - 若 unit 未启动 → start
    #   - 若 unit 已启动 → start 是 no-op(除非 --now 触发的 enable 有变化)
    # 因此这里是幂等的。若启动失败,systemd 会返回非 0,配合 set -e 会中止。
    systemctl enable --now prism-cloud.service
    log_ok "systemd unit 已安装并启动"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 7:健康检查
# ═════════════════════════════════════════════════════════════════════════
health_check() {
    log_step "Step 7/9 · 健康检查 ${HEALTH_URL}"

    # 给 systemd 5 秒完成 uvicorn 冷启动
    for i in 1 2 3 4 5 6 7 8 9 10; do
        if curl -fsS --max-time 3 "${HEALTH_URL}" >/dev/null 2>&1; then
            log_ok "健康检查通过(第 ${i} 次尝试)"
            curl -sS "${HEALTH_URL}" | sed 's/^/        /' || true
            echo
            return 0
        fi
        sleep 1
    done

    log_err "健康检查失败。最近日志:"
    journalctl -u prism-cloud.service -n 40 --no-pager || true
    die "cloud_service 未能在 ${HEALTH_URL} 上正常响应,请检查 systemd 日志"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 8:nginx 配置校验(不 reload)
# ═════════════════════════════════════════════════════════════════════════
nginx_check() {
    log_step "Step 8/9 · nginx 配置校验"

    if ! command -v nginx >/dev/null 2>&1; then
        log_warn "未找到 nginx,跳过配置校验"
        return 0
    fi

    # 若目标不存在,提示手工放置
    if [[ ! -f "${NGINX_CONF_DST}" ]]; then
        log_warn "缺失 ${NGINX_CONF_DST}"
        cat <<EOF

请手工执行(需要把 server_name / ssl_certificate 改成你的真实值):
    sudo cp ${APP_DIR}/${NGINX_CONF_SRC} ${NGINX_CONF_DST}
    # 编辑 ${NGINX_CONF_DST}:
    #   - server_name fusion.maning789link.top   → 你的实际子域名
    #   - ssl_certificate /etc/letsencrypt/live/fusion.maning789link.top/...
    #                                              → 你的实际证书路径
    sudo nginx -t && sudo systemctl reload nginx

**注意**:不要动 /etc/nginx/conf.d/fde.conf (Pay Skill 项目)。
EOF
    else
        log_ok "${NGINX_CONF_DST} 已存在"
    fi

    # 无论如何都跑一次 nginx -t,防止配置语法有问题
    if ! nginx -t 2>&1; then
        log_err "nginx -t 失败。请检查 /etc/nginx/conf.d/ 下所有片段(包括 fde.conf)。"
        die "nginx 配置无效,abort。"
    fi
    log_ok "nginx -t 通过"
}

# ═════════════════════════════════════════════════════════════════════════
# Step 9:总结
# ═════════════════════════════════════════════════════════════════════════
summary() {
    log_step "Step 9/9 · 部署完成"
    cat <<EOF

${LOG_PREFIX} 部署摘要
  工作目录   :${APP_DIR}
  venv       :${VENV_DIR}
  服务单元   :${SYSTEMD_UNIT_DST}
  后端监听   :${BACKEND_HOST}:${BACKEND_PORT}  (仅 loopback,不对外)
  健康端点   :${HEALTH_URL}
  systemd 状态 :$(systemctl is-active prism-cloud.service 2>/dev/null || echo "unknown")
  最近日志   :journalctl -u prism-cloud -n 100 --no-pager

${LOG_PREFIX} 尚未完成(需人工):
  1) 若 ${NGINX_CONF_DST} 不存在,请按脚本上方提示手工放置。
  2) 配置真实子域名 + TLS 证书。
  3) 在云厂商安全组放行 80/443(仅对已备案的域名)。
  4) 前端产物在本地构建,上传到 Pay Skill 项目或其它静态目录(不在这台机器上 build)。
EOF
}

# ═════════════════════════════════════════════════════════════════════════
# main
# ═════════════════════════════════════════════════════════════════════════
main() {
    printf '%s 开始部署 (host=%s, base=%s)\n' \
        "${LOG_PREFIX}" "$(hostname -s 2>/dev/null || echo unknown)" "${BASE_DIR}"

    precheck
    setup_venv
    sync_code
    check_credentials
    init_database
    install_systemd_unit
    health_check
    nginx_check
    summary
}

main "$@"
