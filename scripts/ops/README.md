# scripts/ops — 运维脚本

目前包含:

- `backup_mariadb.sh` — MariaDB (`prism_cloud`) 全量逻辑备份 + 7 天轮转。

> 约定:
> - 所有运维脚本放在 `scripts/ops/`,不放入 `scripts/maintenance/`(那里是本地开发用清理脚本)。
> - 本目录只放**服务器端运行**的脚本;本地调试脚本留在 `scripts/maintenance/` 或 `scripts/utilities/`。
> - 脚本本身**不写死密码**,一律从 `/opt/prism-fusion/.db_credentials/.env` 读。

---

## backup_mariadb.sh

对生产库 `prism_cloud` 做 `mysqldump --single-transaction --routines` 全量备份,gzip 压缩后落到 `/opt/prism-fusion/backups/`,并保留最近 7 天。

### 关键行为

| 项 | 值 |
|---|---|
| 凭据来源 | `/opt/prism-fusion/.db_credentials/.env` 的 `CLOUD_DB_URL` |
| 数据库 | `prism_cloud` (10.11.x @ 127.0.0.1) |
| 输出目录 | `/opt/prism-fusion/backups/` (权限 0700) |
| 文件名 | `prism_cloud_YYYY-MM-DD_HHMMSS.sql.gz` |
| 保留策略 | 删除 `mtime > 7 天` 的旧备份 (`BACKUP_KEEP_DAYS` 可覆盖) |
| 失败行为 | `set -euo pipefail`,任何一步失败即退出,不留下半成品文件 |
| 密码暴露面 | 走 `--defaults-extra-file` + 临时文件 `/dev/shm/...`,退出即删; 密码**不**打印,也不进 `/root/.my.cnf` |

### 一次手动执行

```bash
# 首次运行前,目录应该由 deploy.sh 已创建;没有则手动建
sudo mkdir -p /opt/prism-fusion/backups
sudo chmod 700  /opt/prism-fusion/backups

# 手动跑一次 (在服务器上执行, 不是本机)
sudo bash /opt/prism-fusion/app/scripts/ops/backup_mariadb.sh

# 预期看到两行日志:
#   [backup 2026-10-18_021234] starting backup: db=prism_cloud@127.0.0.1:3306 user=prism -> /opt/prism-fusion/backups/prism_cloud_2026-10-18_021234.sql.gz
#   [backup 2026-10-18_021237] backup done: ... (12.3M)
#   [backup 2026-10-18_021237] rotating backups older than 7 days under /opt/prism-fusion/backups
#   [backup 2026-10-18_021237] retention ok: N backup file(s) kept under /opt/prism-fusion/backups

# 列出当前备份
ls -lh /opt/prism-fusion/backups/prism_cloud_*.sql.gz
```

### 定时任务 (cron)

在服务器上 `sudo crontab -e` 添加一行(每天 02:00 执行):

```cron
0 2 * * * /usr/bin/flock -n /tmp/backup_prism.lock /usr/bin/bash /opt/prism-fusion/app/scripts/ops/backup_mariadb.sh >> /var/log/backup_prism.log 2>&1
```

要点:

- `flock -n` 保证如果上一次还没跑完,这次直接跳过(避免叠加)。
- 日志追加到 `/var/log/backup_prism.log`。日志**不包含密码**,可长期保留。
- 若想更频繁,例如每小时一次,改成 `0 * * * *`。
- 想保留更久,`BACKUP_KEEP_DAYS=14 sudo bash ...` 或者在 cron 里 `BACKUP_KEEP_DAYS=14 env bash ...`(注意 env 前缀必须放在 shell 之前)。

**日志轮转**(可选,防止日志无限增长):

```cron
# /etc/logrotate.d/backup_prism  (需要手工创建)
/var/log/backup_prism.log {
    daily
    rotate 30
    compress
    missingok
    notifempty
}
```

### 恢复步骤

**先决条件**: 备份文件必须能解压并且非空。恢复前先停服务,避免应用写库和 `mysql` 客户端同时操作。

```bash
# 0. 停服务, 避免边导入边被业务改写
sudo systemctl stop prism-cloud

# 1. 校验备份文件本身是完好的 gzip
gzip -t /opt/prism-fusion/backups/prism_cloud_2026-10-17_020000.sql.gz

# 2. 恢复到一个空的 prism_cloud 数据库 (推荐先在测试环境跑一次!)
gunzip < /opt/prism-fusion/backups/prism_cloud_2026-10-17_020000.sql.gz | \
  mysql --user=prism --host=127.0.0.1 --port=3306 prism_cloud
# 如果密码不方便在命令行里暴露, 用 my.cnf:
#   printf '[client]\nuser=prism\npassword=xxx\n' > /tmp/my.cnf
#   chmod 600 /tmp/my.cnf
#   gunzip < xxx.sql.gz | mysql --defaults-extra-file=/tmp/my.cnf prism_cloud
#   rm -f /tmp/my.cnf

# 3. 启动服务
sudo systemctl start prism-cloud
```

**如果要"整库替换"**(把 `prism_cloud` 完全恢复到某个时点):

```bash
# ⚠️  生产环境不建议直接这么做,先在测试环境验证
sudo systemctl stop prism-cloud
mysql --user=prism --host=127.0.0.1 -e "DROP DATABASE prism_cloud; CREATE DATABASE prism_cloud CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
gunzip < /opt/prism-fusion/backups/prism_cloud_YYYY-MM-DD_HHMMSS.sql.gz \
  | mysql --user=prism --host=127.0.0.1 prism_cloud
sudo systemctl start prism-cloud
```

如果 `CLOUD_DB_URL` 指向的主机不是 `127.0.0.1`(例如备份被传到异地机器),恢复时把 `--host` 改成对端 MariaDB 的地址。

### 磁盘 & 存放位置

- **强烈建议**备份目录为 `/opt/prism-fusion/backups/`(与 `deploy/deploy.sh` 约定一致),**不要**放 C 盘或应用工作目录之外的小分区。
- 生产是 Linux (101.43.65.216),`/opt` 一般落在根分区;`lsblk` 或 `df -h` 可以确认剩余空间。
- 每天一次备份的默认压缩率下,库 100 MB 大约对应 10–20 MB gzip;库 1 GB 大约 100–200 MB。留 10× 的余量比较稳妥。
- 如果磁盘紧张,把 `KEEP_DAYS` 调低(如 3),或把旧备份再往 S3/OSS 拉一份后本地只留 3 天。

### 凭据与安全

- 凭据路径: `/opt/prism-fusion/.db_credentials/.env`(由 `deploy/deploy.sh` 校验,权限 0600)。
- 备份文件里**不**含任何账号密码;mysqldump 只导 schema + 数据。
- 临时密码文件 `/dev/shm/.backup_prism_<pid>_pw` 是 RAM 上的 tmpfs,权限 0600,脚本 `trap EXIT` 时删掉。
- **不要**把 `/opt/prism-fusion/backups/` 挂到共享挂载、上传到公网对象存储、或 `scp` 到不信任的机器。
- 若怀疑泄露,立刻 `sudo systemctl stop prism-cloud && sudo rm -rf /opt/prism-fusion/backups/*` 并轮换 `prism@127.0.0.1` 密码。

### 排错

| 现象 | 原因 / 处置 |
|---|---|
| `missing dependency: mysqldump` | 服务器上没有 `MariaDB-client`。`sudo dnf install -y mariadb` |
| `credentials file not found` | `.db_credentials/.env` 缺失或权限不对。重跑 `deploy/deploy.sh` 的 Step 4 |
| `CLOUD_DB_URL must contain a password` | `.env` 里 URL 缺少 `:password@` 段,补上 |
| `mysqldump failed` | 常见是密码错、账号没 `SELECT/LOCK TABLES/RELOAD` 权限、或库名拼错。用同一 URL 手动连一次 mysql 排查 |
| `backup file suspiciously small` | 一般是 dump 内容为空(空库)或权限只读到 0 行。手动 `mysqldump ... \| wc -l` 交叉验证 |
| 磁盘满 | `find /opt/prism-fusion/backups -mtime +2 -delete` 先手动清一批 |

### 已知限制

- **轮转按 mtime 计**: `find -mtime` 依赖文件修改时间。不要用 `touch -d` 篡改备份文件的 mtime,否则轮转会失效。
- **不做异地灾备**: 本脚本只在本机落一份。要跨机器 / 跨云,需要另外配 `rsync`、`rclone` 或对象存储 CLI,并在那一层做加密。
- **不做增量备份**: `mysqldump` 是全量导出。库大之后(>10 GB)可以考虑 `xtrabackup` 做物理备份,但 MariaDB 官方版本自带 `mariabackup`。
- **不保证恢复时间 (RTO)**: 本脚本没有演练脚本,恢复步骤只在需要时手工跑;建议每季度手工演练一次,记录实际耗时。
