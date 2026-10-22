# Prism-Fusion Cloud Service — 部署手册

> 目标服务器:OpenCloudOS 9.6 · 4C / 3.6G RAM(可用 2.8G) / 33G disk
> 反向代理:nginx 1.29.8(仅对外 80/443) · 内部端口:cloud_service → `127.0.0.1:8091`
> 数据库:MariaDB 10.11.18(仅监听 `127.0.0.1:3306`,库 `prism_cloud`,用户 `prism@127.0.0.1`)
> 依赖系统:RHEL 系,包管理用 **`dnf`/`yum`**(不是 `apt`)
>
> **Python 版本**:服务器实测 **Python 3.11.6**(OpenCloudOS 9.6 系统包),`cloud_service` 已在此版本
> 真机跑通 `/health` 与 e2e 用例。CI 基线同为 3.11,与生产一致。本地开发用 3.13.14 也可,但不建议
> 生产环境升级到 3.12+,以免未来踩兼容性坑。

---

## 1. 文件清单

| 文件 | 目标位置(在服务器上) | 说明 |
|---|---|---|
| [`deploy/deploy.sh`](./deploy.sh) | 从 `${APP_DIR}/deploy/deploy.sh` 直接执行 | 幂等部署脚本,不 reload nginx、不生成 secret |
| [`deploy/prism-cloud.service`](./prism-cloud.service) | `/etc/systemd/system/prism-cloud.service` | 由 `deploy.sh` 自动 `cp + daemon-reload + enable --now` |
| [`deploy/nginx-prism-cloud.conf`](./nginx-prism-cloud.conf) | `/etc/nginx/conf.d/prism-cloud.conf` | **需要手工 cp**(子域名 / 证书路径要改),脚本只 `nginx -t` |
| [`deploy/README.md`](./README.md) | — | 本文件 |

---

## 2. 前置准备(人工,一次性)

在服务器上 root shell 完成以下事项,再由 `deploy.sh` 接手:

### 2.1 目录骨架

```bash
sudo mkdir -p /opt/prism-fusion
cd /opt/prism-fusion
sudo git init --bare repo.git          # 方案 B:服务器裸仓库 + 本地 push
```

### 2.2 数据库凭据

假设 MariaDB 里已经建好:
- 库:`prism_cloud`
- 用户:`prism@127.0.0.1`(仅本机等价)

凭据文件:
```bash
sudo mkdir -p /opt/prism-fusion/.db_credentials
sudo chmod 700 /opt/prism-fusion/.db_credentials
sudo tee /opt/prism-fusion/.db_credentials/.env >/dev/null <<'EOF'
CLOUD_DB_URL=mysql+pymysql://prism:<password>@127.0.0.1:3306/prism_cloud
EOF
sudo chmod 600 /opt/prism-fusion/.db_credentials/.env
```

> **本脚本不会自动创建或改写这两个文件**;缺失即报错退出。

### 2.3 应用环境变量

手工创建 `/opt/prism-fusion/.env.cloud`(权限 600),按下面清单填真实值:

#### `.env.cloud` 变量清单(**本手册不写任何真实值**)

分组见 `cloud_service/settings.py` 与 `cloud_service/.env.example`。生产最少需要显式设置以下:

**数据库(可从 `.db_credentials` 自动追加,也可在这里直接写)**
- `CLOUD_DB_URL` — 例:`mysql+pymysql://prism:xxxx@127.0.0.1:3306/prism_cloud?charset=utf8mb4`
  (若不在 `.env.cloud` 里写,`deploy.sh` 会检测 `.db_credentials` 并追加一次;已存在则不重复)

**JWT / 安全**
- `CLOUDJWT_SECRET` — **必填**(未设置则每次重启所有 token 失效)
- `CLOUDJWT_ALGORITHM` — 默认 `HS256`
- `CLOUD_ACCESS_TOKEN_EXPIRE_MINUTES` — 默认 30
- `CLOUD_REFRESH_TOKEN_EXPIRE_DAYS` — 默认 7

**LLM(OpenAI 兼容)**
- `CLOUD_LLM_API_KEY` — **必填**,否则 `/cloud/llm/*` 返回 503
- `CLOUD_LLM_BASE_URL` — 默认 `https://api.siliconflow.cn/v1`
- `CLOUD_LLM_MODEL` — 默认 `deepseek-ai/DeepSeek-V3`

**管理 / HMAC**
- `CLOUD_ADMIN_TOKEN` — **必填**(用于 `/cloud/prompts-export` 二次门禁;
  同时也是线下人工充值管理端 `/cloud/admin/*` 的鉴权凭据 —— 未设置则这三个端点一律 503,fail-closed)
- `CLOUD_HMAC_SECRET` — **必填**(用于 `/cloud/prompts-export` 签名)

**线上支付开关（线下人工充值模式,2026-10-22)**
- `CLOUD_ONLINE_PAYMENT_ENABLED` — 默认 `false`。**当前生产保持 false**:
  网站备案 / ICP 许可证未落地,线上收款不具备合规前提,商业闭环改为
  「加产品方微信 → 人工收款 → 签发注册码 → 用户填入客户端」。
  关闭时 `/cloud/payment/*` 与 `/cloud/points/recharge` 统一返回 `403`
  (`reason=online_payment_disabled` + 人工充值指引),且不启动订单超时 / 对账后台任务。
  **备案到位后设成 `true` 即完整恢复线上支付,不需要重写任何代码。**
- 人工充值管理端(`X-Admin-Token` header + `CLOUD_ADMIN_TOKEN`):
  - `GET  /cloud/admin/users` — 用户列表(含积分余额 / 套餐 / 到期时间)
  - `POST /cloud/admin/points/adjust` — 调整账户积分(`mode=add|set`,可加可减可设定,写流水)
  - `POST /cloud/admin/subscription/extend` — 人工续期
- 注册码激活:`POST /cloud/license/activate` —— 用注册码开通订阅 + 注入注册码携带的积分额度
  (幂等键 = `license_id`,重复激活不会重复加积分)。桌面端对应入口是「设置 → 本地注册码 → 同步到云端」。

**CORS**
- `CLOUD_CORS_ORIGINS` — 例:`https://fusion.maning789link.top,https://<frontend-domain>`

**分布式锁 / 调度后台**
- `CLOUD_REDIS_URL` — 默认 `redis://localhost:6379/0`(`cloud_service/payment/task_guard.py` 读取,
  用于订单超时扫描、对账等后台任务的分布式锁;Redis 不可达时会 fail-open 降级为 lock-free,
  生产建议按第 1 节装 Redis 并收敛到 `127.0.0.1`)

**调度开关**
- `CLOUD_ORDER_TIMEOUT_ENABLED` — 默认 `true`(默认开启,每小时跑一次)
- `CLOUD_ORDER_TIMEOUT_INTERVAL_SECONDS` — 默认 `3600`
- `CLOUD_ORDER_TIMEOUT_HOURS` — 默认 `24`
- `CLOUD_RECONCILE_ENABLED` — 默认 `false`(接入真实商户 adapter 前保持关闭)
- `CLOUD_RECONCILE_INTERVAL_SECONDS` — 默认 `86400`
- `CLOUD_RECONCILE_LOOKBACK_HOURS` — 默认 `24`

**计费额度**
- `CLOUD_FREE_QUOTA` — 默认 `20`
- `CLOUD_PRO_QUOTA` — 默认 `-1`(无限)

**支付(可选,视业务是否启用 C19)**
- `CLOUD_PAYMENT_PRICES` — 例:`{"pro_30":99.0,"pro_365":799.0,"free":0.0}`
- `CLOUD_PAYMENT_NOTIFY_URL` — 例:`/cloud/payment/callback/alipay`
- `CLOUD_PAYMENT_RETURN_URL` — 例:`/payment/success`
- `CLOUD_ALIPAY_SANDBOX` / `CLOUD_ALIPAY_APP_ID` / `CLOUD_ALIPAY_APP_PUBLIC_KEY` / `CLOUD_ALIPAY_SECRET`
- `CLOUD_WECHAT_SANDBOX` / `CLOUD_WECHAT_APP_ID` / `CLOUD_WECHAT_MCHID` / `CLOUD_WECHAT_API_V3_KEY` / `CLOUD_WECHAT_API_SECRET`

`chmod 600 /opt/prism-fusion/.env.cloud`

### 2.4 TLS 证书

假设你用 Let's Encrypt / certbot:
```bash
sudo certbot certonly --webroot -w /var/www/letsencrypt \
  -d fusion.maning789link.top
```

产出路径:
```
/etc/letsencrypt/live/fusion.maning789link.top/fullchain.pem
/etc/letsencrypt/live/fusion.maning789link.top/privkey.pem
```

---

## 3. 部署顺序

### 3.1 首次部署

**在本地**:
```bash
cd Prism-Fusion
git remote add server <your-server>:/opt/prism-fusion/repo.git
git push server main
```

**在服务器**:
```bash
sudo bash /opt/prism-fusion/app/deploy/deploy.sh
```

若 `app/` 目录还不存在,`deploy.sh` 会自动从 `repo.git` clone 一次;
如果 clone 之后 `deploy/` 目录不存在(说明你 push 的分支里没有 deploy 目录),脚本会明确报错。

脚本会依次做:
1. `dnf` 存在检查 + `python3` 版本 + MariaDB active 检查
2. `dnf install -y git python3-pip`(缺失才装)
3. 幂等建 venv + `pip install` cloud_service 最小依赖集合
4. `git clone` / `git pull --ff-only`
5. 校验 `.db_credentials` 与 `.env.cloud`(缺失就 `die`)
6. `init_db()`(幂等建表 + seed prompt 库)
7. 备份旧 unit + `cp + daemon-reload + enable --now`
8. `curl /health`(10 次尝试,间隔 1s)
9. 校验或提示 nginx 配置(见 §4)

### 3.2 nginx 配置(手工)

```bash
sudo cp /opt/prism-fusion/app/deploy/nginx-prism-cloud.conf \
        /etc/nginx/conf.d/prism-cloud.conf

# 编辑子域名 + 证书路径
sudo sed -i \
  -e 's|fusion\.maning789link\.top|<你的真实子域名>|g' \
  /etc/nginx/conf.d/prism-cloud.conf

sudo nginx -t && sudo systemctl reload nginx
```

**不要动** `/etc/nginx/conf.d/fde.conf`(Pay Skill 项目的 server 块)。

### 3.3 前端产物(强烈建议本地构建)

服务器内存只有 2.8G 可用,`next build` 峰值经常 >1.5G,会挤爆 MariaDB 与 Pay Skill。

**本地构建后上传**(推荐):
```bash
# 本地
cd prism_frontend
npm ci
npm run build     # 产出到 prism_frontend/out/ 或 .next/

# 上传到 Pay Skill 项目的静态目录(或专门的静态托管目录)
rsync -av --delete prism_frontend/out/ <server>:/path/to/static/
```

上传完成后确认 nginx 那边静态资源的 `root` 指向即可。

---

## 4. 回滚

### 4.1 应用回滚(代码 / 依赖)

**代码回滚**:
```bash
cd /opt/prism-fusion/app
git log --oneline -20
git revert <bad-commit>          # 生成反向 commit
sudo systemctl restart prism-cloud
```
或(紧急止血):
```bash
git checkout <known-good-commit>
sudo systemctl restart prism-cloud
```

**依赖回滚**:删掉 venv,重跑 `deploy.sh`,脚本会重建:
```bash
sudo rm -rf /opt/prism-fusion/venv
sudo bash /opt/prism-fusion/app/deploy/deploy.sh
```
> 注意:这会跑 pip install 一次,首次约 2-4 分钟。

### 4.2 systemd unit 回滚

`deploy.sh` 每次安装都会把旧 unit 备份到 `/etc/systemd/system/prism-cloud.service.bak.<时间戳>`:
```bash
ls -lt /etc/systemd/system/prism-cloud.service.bak.*
sudo cp /etc/systemd/system/prism-cloud.service.bak.<时间戳> \
        /etc/systemd/system/prism-cloud.service
sudo systemctl daemon-reload
sudo systemctl restart prism-cloud
```

### 4.3 nginx 配置回滚

**永远不要 reload 未通过 `nginx -t` 的配置**。若已经 reload 出问题:
```bash
sudo cp /etc/nginx/conf.d/prism-cloud.conf /etc/nginx/conf.d/prism-cloud.conf.bad
sudo rm /etc/nginx/conf.d/prism-cloud.conf      # 删掉整个 server 块,Pay Skill 不受影响
sudo nginx -t && sudo systemctl reload nginx
```

### 4.4 数据库回滚

`init_db()` 只做 `Base.metadata.create_all()`(DDL 幂等,不 drop),不会破坏数据。
回滚业务数据请用 `mysqldump` 前置备份:
```bash
sudo mysqldump -u prism -p prism_cloud > /tmp/prism_cloud.bak.$(date +%F).sql
```

---

## 5. 常用运维命令

```bash
# 查看服务状态
sudo systemctl status prism-cloud --no-pager
sudo systemctl is-active prism-cloud

# 查看最近日志
sudo journalctl -u prism-cloud -n 200 --no-pager
sudo journalctl -u prism-cloud -f              # 实时

# 手动重启 / 停止
sudo systemctl restart prism-cloud
sudo systemctl stop prism-cloud

# 健康检查
curl -sS http://127.0.0.1:8091/health | jq
curl -sS https://<your-domain>/health | jq

# nginx 单独校验
sudo nginx -t
sudo tail -n 50 /var/log/nginx/prism-cloud.error.log
```

---

## 6. 常见故障

| 现象 | 排查 |
|---|---|
| `prism-cloud.service` 卡在 `activating` | `ExecStartPre` 里检查了 venv 与 `.env.cloud` 是否存在;若你手删了 `.env.cloud` 会直接激活失败。用 `journalctl -u prism-cloud` 定位。 |
| `init_db` 报 `Access denied for user 'prism'@'127.0.0.1'` | 检查 `.db_credentials/.env` 里的 `CLOUD_DB_URL` 密码;或 `mysql -u root -p -e "SHOW GRANTS FOR 'prism'@'127.0.0.1'"`。 |
| `init_db` 报 `Can't connect to MySQL server on '127.0.0.1:3306'` | `systemctl is-active mariadb`;若 inactive,`systemctl start mariadb`。 |
| 健康检查失败但 systemd active | `curl -v http://127.0.0.1:8091/health`;常见原因是 uvicorn 冷启动超过 5s,多试几次;若持续失败,`journalctl -u prism-cloud -n 100` 看栈。 |
| SSE `/cloud/llm/stream` 卡在中间不发数据 | 检查 nginx 里 SSE location 有没有 `proxy_buffering off;` 与 `proxy_read_timeout 300s;`。也检查 CDN(如果有)是否开了 buffering。 |
| 404 到 `/` | 这是 nginx 配置故意返回的。你的前端产物应该在别的 server 块(比如 fde.conf)或者另外的静态目录里。 |

---

## 7. 未在本手册覆盖的(需上层明确)

- **实际子域名**:占位是 `fusion.maning789link.top`,请替换为真实备案域名。
- **TLS 证书路径**:占位是 `/etc/letsencrypt/live/fusion.maning789link.top/...`,请按你的 CA 提供商实际路径修改。
- **`.env.cloud` 真实值**:本手册只列变量名,不列任何 secret。
- **安全组 / 防火墙**:放行 80/443 由你在云厂商控制台操作,脚本不会动。
- **前端静态资源目录**:假设由 Pay Skill 或其他静态 server 托管,不在本手册范围。
