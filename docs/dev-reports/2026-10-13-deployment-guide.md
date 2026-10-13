# Prism-Fusion 线上部署指南(C20)

> 目标:把 SaaS 版 Prism-Fusion 部署到公有云,完成端到端可用。
> 面向对象:**执行部署的另一个 AI agent**。所有步骤都是可复制的命令级步骤;需要外部申请的项以 **[需申请]** 标注;上线 checklist 在第 6 节。
> 生成时间:2026-10-13。基于仓库快照:`cloud_service/` v0.3.0(C12 auth + C13 billing + C14 llm_proxy + C16 client gateway + C19 payment)。

---

## 0. 阅读须知(执行前先看)

- 本指南只覆盖 **云端服务 + 客户端上线配置**,不涉及本地后端打包、浏览器自动化、发布流水线等既有能力。
- 目标云:**阿里云 / 腾讯云**(二者任选其一即可,命令按 Linux 通用写;阿里云默认 Ubuntu 22.04/24.04,腾讯云默认 Ubuntu 22.04/24.04)。
- 目标架构:**客户端 Electron ↔ Nginx/HTTPS ↔ cloud_service(FastAPI + uvicorn) ↔ MySQL + (可选 Redis) ↔ 支付宝/微信 + 云端 LLM**。
- 生产环境**必须显式配置** `CLOUDJWT_SECRET`(否则进程内随机生成,重启所有用户 token 失效——见 `cloud_service/settings.py:41-59`)。
- 支付方式:支付宝 + 微信;LLM 由云端持有 key(客户端零配置)。
- 商业模式:软件订阅(月/年);免费版每月 `CLOUD_FREE_QUOTA` 次调用,PRO 版 `CLOUD_PRO_QUOTA=-1` 表示无限。

---

## 1. 部署架构图(文字版)

```
┌──────────────────────────────────────────────────────────────────┐
│                        用户机器(Electron 客户端)                    │
│  ┌──────────────┐  ┌───────────────┐  ┌────────────────────┐    │
│  │ prism_frontend│  │ prism_backend  │  │  cloud_gateway.py   │   │
│  │  Next.js      │  │ FastAPI:7000  │  │  LAOMA_CLOUD_BASE_URL│  │
│  └──────────────┘  └───────────────┘  └────────────────────┘    │
└───────────────────────────┬──────────────────────────────────────┘
                            │  HTTPS + Bearer JWT
                            ▼
┌──────────────────────────────────────────────────────────────────┐
│                     云端(阿里云 ECS / 腾讯云 CVM)                    │
│   ┌───────────────────┐      ┌──────────────────────────┐       │
│   │  Nginx  443/80    │─────▶│  cloud_service:8000       │       │
│   │  (TLS + 反代)      │      │  FastAPI + uvicorn × 4    │       │
│   └───────────────────┘      │  /cloud/auth/*            │       │
│                              │  /cloud/subscription      │       │
│                              │  /cloud/usage             │       │
│                              │  /cloud/license           │       │
│                              │  /cloud/llm/chat/prompts  │       │
│                              │  /cloud/payment/*         │       │
│                              └──────┬───────────────┬────┘       │
│                                     │              │              │
│                        ┌────────────▼──┐    ┌──────▼─────────┐   │
│                        │ RDS MySQL      │    │ (Redis 可选)     │   │
│                        │ 用户/订阅/用量/订单 │    │ 限流/缓存        │   │
│                        └────────────────┘    └─────────────────┘   │
└───────────────┬──────────────────────────────┬──────────────────────┘
                │                              │
                ▼                              ▼
      ┌──────────────────┐           ┌──────────────────┐
      │ 支付宝 / 微信支付  │           │  云端 LLM 服务    │
      │ 商户号 + 证书      │           │  CLOUD_LLM_*      │
      │  异步回调 URL      │           │  (DeepSeek/GPT...) │
      └──────────────────┘           └──────────────────┘
```

**关键约束**:
- 云端必须持有 LLM key(客户端 0 接触),通过 `POST /cloud/llm/chat` 代理。
- 支付宝/微信的**异步回调**必须公网可达,且 HTTPS(`POST /cloud/payment/callback/{channel}`)。
- 客户端双通道:LLM/认证/订阅/支付 → 云端;浏览器自动化/文件/发布 → 本地 `127.0.0.1:7000`。
- 云端不可达时客户端降级为 `basic tier + 用户自配 LLM key`(见 `prism_backend/fusion_ai/cloud_gateway.py:525-543`)。

---

## 2. 云资源准备

### 2.1 资源清单

| 资源 | 阿里云 | 腾讯云 | 用途 | 规格建议 | 备注 |
|---|---|---|---|---|---|
| 域名 | [需申请] 域名服务 | [需申请] 域名服务 | 客户端访问 | 建议 `api.<brand>.com` | **[需申请 + 备案]** |
| ECS / CVM | ECS | CVM | 部署 Nginx + cloud_service | **2C4G 起,推荐 4C8G**;系统 Ubuntu 22.04+ | 带宽 5M 起;系统盘 100G SSD |
| RDS MySQL | RDS MySQL | 云数据库 MySQL | 用户 / 订阅 / 用量 / 订单 | 2C4G,100G 起,SSD | 建议内网连接 |
| Redis | Redis 云数据库 | 云数据库 Redis | 限流 / 会话缓存 | 1G 起 | **可选**,不做则本地缓存 |
| HTTPS 证书 | 数字证书服务 | SSL 证书服务 | TLS | 免费 DV 即可 | 或用 Let's Encrypt |
| 对象存储 | OSS | COS | 静态资源 / 备份 / 客户端下载 | 按需 | **可选** |
| KMS(密钥管理) | KMS | KMS 密钥管理系统 | LLM key 存储 | 按需 | **可选**;未启用则用 env 注入 |
| 弹性公网 IP | EIP | 公网 IP | 域名解析指向 | 按需 | 与 ECS 绑定即可 |
| 内容分发(CDN) | CDN | CDN | 客户端安装包分发 | 按需 | 后续迭代再加 |

**[需申请] 项提示**:
- **ICP 备案**:大陆境内 ECS 公网 IP 必须完成 ICP 备案才能对公网提供 80/443 服务。阿里云 → [阿里云备案](https://beian.aliyun.com/);腾讯云 → [腾讯云备案](https://cloud.tencent.com/product/ba)。周期通常 7-20 工作日。**未完成备案前,80/443 端口不可对外开放**。
- **商户号**:支付宝企业账户 → [支付宝开放平台](https://open.alipay.com/);微信支付商户号 → [微信支付商户平台](https://pay.weixin.qq.com/)。均需企业资质,周期 3-10 工作日。
- **数字证书**:阿里云/腾讯云都提供免费的 DV 证书;或用 certbot 自动生成 Let's Encrypt 证书。

### 2.2 网络与安全组

ECS 安全组(入站,来源 `0.0.0.0/0`):
- 80 / 443:TCP(公网)
- 22:TCP(**限制为公司出口 IP**,不要全开)

ECS 安全组(入站,来源 `内网 CIDR`):
- 3306(MySQL,仅在 RDS 与 ECS 同 VPC 时;通常 RDS 单独开白名单)

RDS 白名单:
- 只加 ECS 的内网 IP(阿里云:`rm-bp1xxx.mysql.rds.aliyuncs.com`;腾讯云类似)
- 生产**不要**加 `0.0.0.0/0`

### 2.3 SSH 登录约定

本指南后续命令都假定:
- 已用密钥登录 ECS:`ssh root@<ecs_public_ip>`
- 已 `apt update && apt upgrade -y`(Ubuntu 22.04/24.04)
- 已安装 `python3 python3-venv python3-pip nginx mysql-client git curl`

---

## 3. cloud_service 部署

### 3.1 目录与代码获取

```bash
# 建议目录布局
mkdir -p /opt/prism-fusion/cloud_service
cd /opt/prism-fusion/cloud_service

# 从代码仓库拉取(二选一)
# 方式 A:git clone
git clone <你的仓库地址> repo
cp -r repo/cloud_service/. /opt/prism-fusion/cloud_service/

# 方式 B:scp/rsync 从开发机拷贝(推荐用于首次)
rsync -avz ./cloud_service/ user@<ecs_ip>:/opt/prism-fusion/cloud_service/
```

### 3.2 Python 依赖

```bash
# 创建虚拟环境
python3 -m venv /opt/prism-fusion/venv
source /opt/prism-fusion/venv/bin/activate

# 安装 cloud_service 生产所需依赖
pip install --upgrade pip wheel

# cloud_service 直接依赖(全部来自仓库源码 import 与 requirements.txt 交叉核对)
pip install \
  'fastapi==0.133.1' \
  'uvicorn[standard]==0.41.0' \
  'starlette==1.3.1' \
  'sqlalchemy==2.0.52' \
  'pydantic==2.13.4' \
  'pydantic-settings==2.15.0' \
  'python-dotenv' \
  'httpx' \
  'openai' \
  'pyjwt' \
  'bcrypt' \
  'pymysql' \
  'loguru' \
  'gunicorn' \
  'cryptography'

# 可选(如启用 Redis / Alembic 迁移 / Celery 任务队列)
pip install redis alembic celery
```

**说明**:
- `pyjwt` 包名在 Python 里是 `import jwt`,见 `cloud_service/auth/security.py:13`。
- `bcrypt` 是硬依赖,`cloud_service/auth/security.py:15` 用它做密码哈希。
- `pymysql` 是 MySQL 生产驱动,`db_url` 前缀 `mysql+pymysql://` 时必需。
- `cryptography` 是支付真实渠道接入后的 RSA2/AES-256-GCM 依赖(当前代码 mock 阶段不强制,建议一并安装)。
- **不要**在生产 `pip install` 本地开发依赖 `pytest / black / flake8 / ruff`(见 `requirements-dev.txt`)。

### 3.3 环境变量清单(逐项)

> 建议写到 `/opt/prism-fusion/.env.cloud`,systemd 加载。chmod 600,属主 root。

```bash
# ── 应用基础 ────────────────────────────────────────────────────
CLOUD_APP_NAME="Prism-Fusion Cloud"
CLOUD_DEBUG="0"                          # 生产务必 0;开了 debug 会打印 traceback

# ── JWT(⚠️ 生产必须显式配置)────────────────────────────────────
# 生成: python -c "import secrets; print(secrets.token_urlsafe(48))"
CLOUDJWT_SECRET="<替换为强随机 64+ 字符字符串>"
CLOUDJWT_ALGORITHM="HS256"
CLOUD_ACCESS_TOKEN_EXPIRE_MINUTES="30"
CLOUD_REFRESH_TOKEN_EXPIRE_DAYS="7"

# ── 数据库(MySQL 推荐)──────────────────────────────────────────
# 格式: mysql+pymysql://USER:PASSWORD@HOST:3306/DATABASE?charset=utf8mb4
CLOUD_DB_URL="mysql+pymysql://prism:P@ssw0rdStr0ng@rm-xxx.mysql.rds.aliyuncs.com:3306/prism_cloud?charset=utf8mb4"

# ── LLM 代理(云端持有 key)──────────────────────────────────────
CLOUD_LLM_API_KEY="<替换为实际 API key>"
CLOUD_LLM_BASE_URL="https://api.siliconflow.cn/v1"     # 或 https://api.openai.com/v1 等
CLOUD_LLM_MODEL="deepseek-ai/DeepSeek-V3"                # 与 base_url 匹配

# ── Prompt 导出密钥管理(离线版打包用)────────────────────────────
# 生成: python -c "import secrets; print(secrets.token_urlsafe(48))"
CLOUD_ADMIN_TOKEN="<替换为强随机字符串,离线构建脚本用>"
CLOUD_HMAC_SECRET="<替换为强随机字符串,离线构建期 HMAC 校验用>"

# ── 订阅额度(每月上限;0=禁用,-1=无限)───────────────────────────
CLOUD_FREE_QUOTA="20"
CLOUD_PRO_QUOTA="-1"

# ── 支付通用 ────────────────────────────────────────────────────
# 回调 URL 必须是公网可达 HTTPS
CLOUD_PAYMENT_NOTIFY_URL="https://api.your-brand.com/cloud/payment/callback"
CLOUD_PAYMENT_RETURN_URL="https://www.your-brand.com/payment/success"
# 价格表(可选,JSON);不配用默认 {pro_30:99, pro_365:799, free:0}
CLOUD_PAYMENT_PRICES='{"pro_30": 99.00, "pro_365": 799.00, "free": 0.00}'

# ── 支付宝(企业商户号)───────────────────────────────────────────
CLOUD_ALIPAY_SANDBOX="0"                                    # 0=生产 1=沙箱
CLOUD_ALIPAY_APP_ID="<支付宝 APPID,open.alipay.com 获取>"   # [需申请]
CLOUD_ALIPAY_PRIVATE_KEY="<商户 RSA2 私钥,PKCS8 Base64>"     # [需申请]
CLOUD_ALIPAY_PUBLIC_KEY="<支付宝平台公钥>"                   # [需申请]
# 二选一,当前代码优先 APP_PUBLIC_KEY
CLOUD_ALIPAY_APP_PUBLIC_KEY="<支付宝应用公钥>"
CLOUD_ALIPAY_SECRET="<沙箱/mock 用;生产留空>"

# ── 微信支付(企业商户号)─────────────────────────────────────────
CLOUD_WECHAT_SANDBOX="0"                                    # 0=生产 1=沙箱
CLOUD_WECHAT_APP_ID="<微信开放平台 APPID>"                  # [需申请]
CLOUD_WECHAT_MCHID="<微信支付商户号 mch_id>"                 # [需申请]
CLOUD_WECHAT_API_V3_KEY="<APIv3 密钥,32 字节>"              # [需申请]
CLOUD_WECHAT_API_SECRET="<APIv2 密钥;v3 场景下留空>"
```

**变量说明速查**:

| 变量 | 是否必需 | 默认/回退 | 用途 | 出处 |
|---|---|---|---|---|
| `CLOUDJWT_SECRET` | ⚠️ 生产必需 | 进程内随机(每次重启失效) | JWT 签名密钥 | `settings.py:41-59` |
| `CLOUD_DB_URL` | ⚠️ 生产必需 | `sqlite:///cloud_service/cloud.db` | 数据库连接串 | `settings.py:62-66` |
| `CLOUD_LLM_API_KEY` | ⚠️ LLM 必需 | 未设置 → `/cloud/llm/chat` 返回 503 | 云端 LLM key | `llm_client.py:68-74` |
| `CLOUD_LLM_BASE_URL` | 可选 | `https://api.siliconflow.cn/v1` | LLM 网关地址 | `llm_client.py:24, 62-63` |
| `CLOUD_LLM_MODEL` | 可选 | `deepseek-ai/DeepSeek-V3` | 默认模型 | `llm_client.py:25, 63` |
| `CLOUD_ADMIN_TOKEN` | ⚠️ prompts-export 必需 | 未设 → 503 | 离线版构建身份凭证 | `llm_proxy/router.py:294-300` |
| `CLOUD_HMAC_SECRET` | 可选 | 回退到 JWT secret | HMAC-SHA256 签名 | `llm_proxy/router.py:303-308` |
| `CLOUD_FREE_QUOTA` | 可选 | 20 | 免费版月度额度 | `settings.py:83` |
| `CLOUD_PRO_QUOTA` | 可选 | -1(无限) | PRO 版月度额度 | `settings.py:85` |
| `CLOUD_PAYMENT_NOTIFY_URL` | 支付必需 | `/cloud/payment/callback/{ch}` | 支付异步回调 | `payment/router.py:106` |
| `CLOUD_PAYMENT_RETURN_URL` | 支付必需 | `/payment/success` | 支付完成后跳转 | `payment/router.py:110` |
| `CLOUD_PAYMENT_PRICES` | 可选 | `{pro_30:99, pro_365:799, free:0}` | 价格表 JSON | `payment/router.py:75-86` |
| `CLOUD_ALIPAY_APP_ID` | 支付宝必需 | `MOCK_ALIPAY_APP_ID` | 支付宝商户 APPID | `payment/alipay.py:44` |
| `CLOUD_ALIPAY_PRIVATE_KEY` | 支付宝生产必需 | 无 → mock 签名 | 商户 RSA2 私钥 | `payment/alipay.py:39-49` |
| `CLOUD_ALIPAY_PUBLIC_KEY` | 支付宝生产必需 | 无 → mock 签名 | 支付宝平台公钥 | `payment/alipay.py:39-49` |
| `CLOUD_WECHAT_APP_ID` | 微信必需 | `MOCK_WECHAT_APP_ID` | 微信开放平台 APPID | `payment/wechat.py:40` |
| `CLOUD_WECHAT_MCHID` | 微信必需 | `MOCK_MCH_ID` | 微信商户号 | `payment/wechat.py:41` |
| `CLOUD_WECHAT_API_V3_KEY` | 微信生产必需 | 无 → mock 签名 | APIv3 密钥 | `payment/wechat.py:44-48` |

**安全约束**:
- 所有 `*_KEY` / `*_SECRET` / `*_TOKEN` **绝不进入 git**,`.gitignore` 应含 `*.env`。
- `.env.cloud` 建议 chmod 600,属主 `root`;systemd 通过 `EnvironmentFile` 加载。
- 敏感变量不要写入 shell history。用 `.env` 文件而不是 `export`。
- 定期轮转 `CLOUDJWT_SECRET` / `CLOUD_ADMIN_TOKEN` / `CLOUD_HMAC_SECRET`。**修改 JWT secret 会导致所有已登录用户需重新登录**。

### 3.4 数据库初始化

**MySQL 建库**:

```sql
-- 在 RDS 控制台或 mysql 客户端执行
CREATE DATABASE prism_cloud CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'prism'@'%' IDENTIFIED BY '<强密码>';
GRANT ALL PRIVILEGES ON prism_cloud.* TO 'prism'@'%';
FLUSH PRIVILEGES;
```

**初始化表结构**(cloud_service 自带幂等建表):

```bash
source /opt/prism-fusion/venv/bin/activate
cd /opt/prism-fusion/cloud_service
export $(grep -v '^#' /opt/prism-fusion/.env.cloud | xargs)

# 幂等建表 + 种 prompt 库
python -c "from cloud_service.db import init_db; init_db()"
```

**验证**:

```bash
mysql -h <rds-host> -u prism -p prism_cloud -e "SHOW TABLES;"
# 应看到:users / subscriptions / usages / prompts / orders(如已启用 C19)
```

**建议:引入 Alembic 迁移**(首次上线后):

```bash
pip install alembic
alembic init migrations
# 编辑 migrations/env.py 引入 cloud_service.db.Base.metadata
# alembic revision --autogenerate -m "init schema"
# alembic upgrade head
```

### 3.5 systemd 服务

**方法 A(推荐,轻量):多进程 uvicorn**

创建 `/etc/systemd/system/prism-cloud.service`:

```ini
[Unit]
Description=Prism-Fusion Cloud Service (FastAPI + uvicorn)
After=network-online.target mysql.service redis.service
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/prism-fusion/cloud_service
EnvironmentFile=/opt/prism-fusion/.env.cloud

# uvicorn 生产配置:4 worker + 4 thread(总并发 ~16)
# 若单进程吞吐够,可用 --workers 1 + --http h11 简化调试
ExecStart=/opt/prism-fusion/venv/bin/uvicorn \
    cloud_service.main:app \
    --host 127.0.0.1 \
    --port 8000 \
    --workers 4 \
    --http h11 \
    --timeout-keep-alive 65 \
    --proxy-headers \
    --forwarded-allow-ips '*' \
    --log-level info \
    --access-log

ExecReload=/bin/kill -s HUP $MAINPID
Restart=always
RestartSec=3
KillMode=mixed

# 资源限制(2C4G 起步;可按实际调优)
LimitNOFILE=65536
TasksMax=4096

# 安全加固
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadOnlyPaths=/opt/prism-fusion/cloud_service

# 日志
StandardOutput=journal
StandardError=journal
SyslogIdentifier=prism-cloud

[Install]
WantedBy=multi-user.target
```

启动:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now prism-cloud
sudo systemctl status prism-cloud --no-pager
journalctl -u prism-cloud -f     # 观察日志
```

**方法 B(重量级):gunicorn + uvicorn worker**

```ini
ExecStart=/opt/prism-fusion/venv/bin/gunicorn \
    cloud_service.main:app \
    -k uvicorn.workers.UvicornWorker \
    -b 127.0.0.1:8000 \
    -w 4 \
    --timeout 120 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -
```

其他配置同方法 A。**首次上线推荐方法 A**,简单可靠。

**手动验证启动**:

```bash
curl http://127.0.0.1:8000/health
# → {"status":"ok","service":"cloud","version":"0.3.0"}

curl http://127.0.0.1:8000/cloud/llm/health
# → {"api_key_configured":true, "base_url":"https://api.siliconflow.cn/v1", "model":"deepseek-ai/DeepSeek-V3", "prompt_count":{...}}
```

### 3.6 Nginx 反代 + HTTPS

**安装 nginx**:

```bash
apt install -y nginx
```

**配置 `/etc/nginx/sites-available/prism-cloud`**:

```nginx
# HTTP → HTTPS 重定向(先放行 certbot 验证)
server {
    listen 80;
    listen [::]:80;
    server_name api.your-brand.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}

# HTTPS 主配置
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name api.your-brand.com;

    # Let's Encrypt 证书路径(certbot 生成后自动放这里)
    ssl_certificate     /etc/letsencrypt/live/api.your-brand.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.your-brand.com/privkey.pem;

    # SSL 安全配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # 安全响应头
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 上传大小限制(支付/文件回调可能带较大 body)
    client_max_body_size 20M;

    # 日志格式
    log_format prism '$remote_addr - [$time_local] "$request" '
                     '$status $body_bytes_sent "$http_referer" "$http_user_agent"';
    access_log /var/log/nginx/prism-cloud.access.log prism;
    error_log  /var/log/nginx/prism-cloud.error.log warn;

    # 上游:uvicorn 4 worker
    upstream cloud_service {
        server 127.0.0.1:8000;
        keepalive 32;
    }

    # 存活探针(允许公网访问,便于 LB / 监控)
    location = /health {
        access_log off;
        proxy_pass http://cloud_service;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    # 所有 /cloud/* 请求
    location /cloud/ {
        proxy_pass http://cloud_service;
        proxy_http_version 1.1;

        # 保留真实客户端 IP
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 长连接支持(LLM 响应可能较慢)
        proxy_connect_timeout 15s;
        proxy_send_timeout 120s;
        proxy_read_timeout 120s;
        proxy_buffering off;
    }

    # 支付异步回调 —— 支付宝/微信要求快速响应,单独配置
    location /cloud/payment/callback/ {
        proxy_pass http://cloud_service;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 30s;
    }

    # 兜底:非 /cloud 前缀直接 404
    location / {
        return 404;
    }
}
```

**启用配置**:

```bash
ln -sf /etc/nginx/sites-available/prism-cloud /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

**签发证书(certbot)**:

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d api.your-brand.com --non-interactive --agree-tos -m admin@your-brand.com
# 自动续期:certbot 已装 systemd timer,无需手动配置
systemctl list-timers | grep certbot
```

**或用阿里云/腾讯云证书**:把证书复制到 `/etc/letsencrypt/live/api.your-brand.com/` 或改 nginx 配置中的路径。

### 3.7 (可选)Redis

cloud_service 当前不硬依赖 Redis,但为限流 / 未来缓存预留。若启用:

```bash
apt install -y redis-server
systemctl enable --now redis
redis-cli ping     # → PONG
```

在 `.env.cloud` 追加:

```bash
CLOUD_REDIS_URL="redis://127.0.0.1:6379/0"
```

---

## 4. 支付配置

### 4.1 支付宝 [需申请]

**申请流程**:

1. 登录 [支付宝开放平台](https://open.alipay.com/),用**企业资质**注册开发者账号。
2. 创建应用 → 拿到 `APPID`(对应 `CLOUD_ALIPAY_APP_ID`)。
3. 开发工具 → 密钥管理 → 生成**应用公钥密钥对**(推荐 RSA2)。
4. 把**应用公钥**上传到开放平台;平台返回**支付宝公钥**(对应 `CLOUD_ALIPAY_PUBLIC_KEY`)。
5. **应用私钥**保存本地(对应 `CLOUD_ALIPAY_PRIVATE_KEY`)。
6. 产品开通:**电脑网站支付**(`alipay.trade.page.pay`),用于用户 Web 端跳转支付。
7. 配置异步通知 URL:填 `https://api.your-brand.com/cloud/payment/callback/alipay`。

**填入 env**:

```bash
CLOUD_ALIPAY_SANDBOX="0"                       # 生产
CLOUD_ALIPAY_APP_ID="2021000000000000"         # 你的 APPID
CLOUD_ALIPAY_PRIVATE_KEY="<-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY----->"
CLOUD_ALIPAY_PUBLIC_KEY="<-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY----->"
CLOUD_ALIPAY_APP_PUBLIC_KEY="<-----BEGIN PUBLIC KEY-----\n(你的应用公钥)\n-----END PUBLIC KEY----->"
```

**⚠️ 当前状态**:代码里 `cloud_service/payment/alipay.py` 仍是 **mock 沙箱签名**(HMAC-SHA256),生产接入前需要:
1. 把 `create_payment` 改成实际调用 `alipay.trade.page.pay` OpenAPI(RSA2 签名,返回 form_html)。
2. 把 `verify_callback` 改成用支付宝公钥做 RSA2 验签。
3. 参考官方 SDK:[alipay-sdk-python](https://github.com/alipay/alipay-sdk-python)。

### 4.2 微信支付 [需申请]

**申请流程**:

1. 登录 [微信开放平台](https://open.weixin.qq.com/),创建公众号 → 拿到 `APPID`(对应 `CLOUD_WECHAT_APP_ID`)。
2. 登录 [微信支付商户平台](https://pay.weixin.qq.com/),申请商户号 → 拿到 `mch_id`(对应 `CLOUD_WECHAT_MCHID`)。
3. 商户平台 → 账户中心 → API 安全 → 设置 **APIv3 密钥**(32 字节,对应 `CLOUD_WECHAT_API_V3_KEY`)。
4. 商户平台 → API 安全 → API 证书 → 申请 **API 证书**(`apiclient_cert.pem` + `apiclient_key.pem`),用于服务端签名。
5. 商户平台 → 产品中心 → 开通**Native 支付**(扫码支付),用于客户端生成二维码。
6. 配置回调 URL:填 `https://api.your-brand.com/cloud/payment/callback/wechat`,平台需下载 API 证书校验。

**填入 env**:

```bash
CLOUD_WECHAT_SANDBOX="0"                       # 生产
CLOUD_WECHAT_APP_ID="wx0000000000000000"       # 你的 APPID
CLOUD_WECHAT_MCHID="1600000000"                # 你的 mch_id
CLOUD_WECHAT_API_V3_KEY="<32 字节 APIv3 密钥>"
```

**⚠️ 当前状态**:代码里 `cloud_service/payment/wechat.py` 仍是 **mock 沙箱签名**。生产接入前需要:
1. 用 `wechatpay-python` SDK(推荐)或 `wechatpy`,实现 `POST /v3/pay/transactions/native` 拿到 `code_url`。
2. 用平台证书(Apiv3 密钥 + mch_id + serial_no)解密回调 resource(WECHATPAY-SIGNATURE header)。
3. 证书轮换自动化(每 90 天提醒 / 或接入证书下载接口)。

### 4.3 支付回调 URL 配置

代码里有两个 env:

| 变量 | 用途 | 建议值 |
|---|---|---|
| `CLOUD_PAYMENT_NOTIFY_URL` | 异步回调(支付宝 notify_url / 微信 notify_url) | `https://api.your-brand.com/cloud/payment/callback/{channel}` |
| `CLOUD_PAYMENT_RETURN_URL` | 支付完成后同步跳转(浏览器) | `https://www.your-brand.com/payment/success?order_no={order_no}` |

**注意**:
- **Notify URL 是服务端到服务端**,不带 order_no 查询参数;order_no 在 body 里(`out_trade_no` 字段)。
- **Return URL 是用户浏览器跳转**,通常要处理订单确认页。
- 支付宝**要求** Notify URL 是公网 HTTPS,不允许内网 IP 或未备案域名。
- 微信**要求** Notify URL 域名已备案、且已上传 API 证书到商户平台。

**沙箱测试**(代码支持):

```bash
# 沙箱模式
CLOUD_ALIPAY_SANDBOX="1"
CLOUD_WECHAT_SANDBOX="1"
```

---

## 5. 客户端配置

客户端配置涉及**云端 URL 注入**,分三处。

### 5.1 后端 Python:LAOMA_CLOUD_BASE_URL

`prism_backend/fusion_ai/cloud_gateway.py:42-46` 读取:

```python
_ENV_CLOUD_BASE_URL = "LAOMA_CLOUD_BASE_URL"
_DEFAULT_CLOUD_BASE_URL = "https://api.prism.local"
```

**注入方式**(选一):

- **环境变量**:进程启动前 `export LAOMA_CLOUD_BASE_URL=https://api.your-brand.com`(不带 `/cloud` 后缀,代码自动拼)。
- **打包时写入配置文件**:在客户端资源目录下放 `cloud_config.ini`,启动时读取。
- **首次启动 UI 配置**:提供设置界面让用户填,写入 `~/.prism-fusion/config.json`。

**生产建议值**:`https://api.your-brand.com`(不带 `/cloud`,不带尾部斜杠)。

### 5.2 前端 Next.js:cloudBaseUrl

`prism_frontend/src/lib/env.ts:47-49` 读取:

```typescript
export const cloudBaseUrl = normalizeCloudBaseUrl(
  process.env.NEXT_PUBLIC_CLOUD_URL ?? process.env.LAOMA_CLOUD_BASE_URL
)
```

**注入方式**(build-time,浏览器端可见):

```bash
cd prism_frontend
cat > .env.local <<EOF
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:7000
NEXT_PUBLIC_CLOUD_URL=https://api.your-brand.com
EOF
npm run build
```

**⚠️ `NEXT_PUBLIC_` 前缀会被打进浏览器 bundle**,不能放敏感信息(比如密钥)。只放**公开的云端域名**。

### 5.3 Electron 打包(cloudBaseUrl 注入)

`desktop-electron/package.json` 使用 electron-builder。打包脚本 `scripts/packaging/build-package.bat` 会:
1. 构建 frontend Next.js standalone。
2. 构建 Python 后端服务(PyInstaller)。
3. 打包 Electron 应用。

**客户端上线前**:

```bash
# 1. 前端构建(注入 cloud URL)
cd prism_frontend
NEXT_PUBLIC_CLOUD_URL=https://api.your-brand.com NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:7000 npm run build

# 2. 打包客户端
cd desktop-electron
set LAOMA_CLOUD_BASE_URL=https://api.your-brand.com   # Windows
export LAOMA_CLOUD_BASE_URL=https://api.your-brand.com # Linux/Mac
set LAOMA_AUTO_YES=1
..\scripts\packaging\build-package.bat

# 3. 输出目录:desktop-electron/dist-out/vN/
```

**验证注入**:

```bash
# 打包完解压 asar 检查
npx asar extract dist-out/v1/win-unpacked/resources/app.asar /tmp/app
grep -r "your-brand.com" /tmp/app 2>/dev/null | head
```

### 5.4 客户端本地配置目录

首次登录后,客户端会:
- 创建 `~/.prism-fusion/credentials.json`(存 JWT access + refresh token,chmod 600)
- Windows 上 Electron 环境可用 `ELECTRON_SAFE_STORAGE` 环境变量切换到系统加密存储(DPAPI / Keychain)

**卸载时**记得清理 `~/.prism-fusion/` 避免残留凭证。

---

## 6. 上线 Checklist

### 6.1 资源准备

- [ ] 域名已注册(`api.your-brand.com` + `www.your-brand.com`)
- [ ] **ICP 备案**已提交/通过 [需申请]
- [ ] 阿里云/腾讯云账号已实名认证
- [ ] ECS 已创建(2C4G 起,Ubuntu 22.04/24.04)
- [ ] RDS MySQL 已创建(2C4G,100G SSD),ECS 内网可达
- [ ] Redis(可选)已创建或本地安装
- [ ] HTTPS 证书已签发(certbot 或云商 DV 证书)
- [ ] 支付宝企业商户号已开通 [需申请],拿到 APPID + RSA2 密钥对 + 支付宝公钥
- [ ] 微信支付商户号已开通 [需申请],拿到 APPID + mch_id + APIv3 密钥 + API 证书

### 6.2 云端部署

- [ ] ECS 已 `apt update && apt upgrade -y`,安装了 `python3 python3-venv python3-pip nginx mysql-client git curl`
- [ ] `/opt/prism-fusion/cloud_service/` 已从代码仓库复制/克隆
- [ ] Python 虚拟环境 `/opt/prism-fusion/venv` 已创建,依赖已装(fastapi/uvicorn/sqlalchemy/pyjwt/bcrypt/httpx/openai/pymysql/loguru/gunicorn)
- [ ] `.env.cloud` 已写入完整环境变量(JWT_SECRET / DB_URL / LLM / 支付宝 / 微信)
- [ ] `chmod 600 /opt/prism-fusion/.env.cloud`
- [ ] 数据库已初始化:`python -c "from cloud_service.db import init_db; init_db()"`
- [ ] `/etc/systemd/system/prism-cloud.service` 已创建并 `systemctl enable --now prism-cloud`
- [ ] Nginx 配置 `/etc/nginx/sites-available/prism-cloud` 已启用
- [ ] certbot 证书已签发,`systemctl list-timers` 看到续期定时任务
- [ ] 安全组已开放 80/443,RDS 白名单已加 ECS 内网 IP

### 6.3 联调验证

- [ ] `curl https://api.your-brand.com/health` → `{"status":"ok",...}`
- [ ] `curl https://api.your-brand.com/cloud/llm/health` → `api_key_configured:true`
- [ ] `curl -X POST https://api.your-brand.com/cloud/auth/register -d '{"username":"test01","email":"t@t.com","password":"Test12345!"}'` → 201
- [ ] `curl -X POST https://api.your-brand.com/cloud/auth/login -d '{"username":"test01","password":"Test12345!"}'` → 拿到 JWT
- [ ] 带 Bearer 访问 `/cloud/subscription` → `plan:"free", quota:20`
- [ ] 用 JWT 调 `/cloud/llm/chat` 传 `prompt_name` → 返回 LLM 结果
- [ ] 用沙箱模式支付 `curl -X POST /cloud/payment/create_order -d '{"plan":"free","days":30,"channel":"alipay"}'` → 拿到 pay_params
- [ ] 用沙箱模式回调 `curl -X POST /cloud/payment/callback/alipay -d '<mock body>'` → 订单变 paid
- [ ] `journalctl -u prism-cloud -n 100` 无异常堆栈

### 6.4 客户端发布

- [ ] `prism_frontend/.env.local` 已配 `NEXT_PUBLIC_CLOUD_URL=https://api.your-brand.com`
- [ ] `prism_frontend` 已 `npm run build`
- [ ] `desktop-electron` 打包产物已生成(`dist-out/vN/*.exe`)
- [ ] 打包产物上传到 OSS/COS 或 GitHub Releases
- [ ] 客户端启动后**用户注册/登录**成功
- [ ] 客户端**首次调用 AI** 走云端成功
- [ ] 客户端**订阅升级**(支付宝/微信)成功

### 6.5 灰度 & 监控

- [ ] 先给 5-10 个内测用户,观察 24-48 小时
- [ ] ECS 云监控已启用(CPU / 内存 / 网络 / 磁盘)
- [ ] RDS 备份策略已配置(每日自动备份,保留 7 天以上)
- [ ] Nginx 日志开启轮转(`logrotate /etc/logrotate.d/nginx`)
- [ ] 关键告警:5xx 错误率 > 1% / 云端响应 P99 > 5s / DB 连接池打满
- [ ] 客户端反馈渠道已建立(邮件 / 客服入口)

---

## 7. 端到端验收

### 7.1 注册 → 登录

```bash
# 1. 注册
curl -X POST https://api.your-brand.com/cloud/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice@example.com","password":"Alice!2345"}'
# → 201 {"id":1,"username":"alice",...}

# 2. 登录
curl -X POST https://api.your-brand.com/cloud/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"Alice!2345"}'
# → {"access_token":"...","refresh_token":"...","expires_in":1800}

# 3. 刷新 token
curl -X POST https://api.your-brand.com/cloud/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<refresh_token>"}'
# → 新的 access_token

# 4. 获取当前用户
curl -H "Authorization: Bearer <access_token>" \
  https://api.your-brand.com/cloud/auth/me
```

### 7.2 免费额度

```bash
TOKEN=*** -s -X POST https://api.your-brand.com/cloud/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","password":"Alice!2345"}' \
  | jq -r .access_token)

# 查看当前订阅与用量
curl -H "Authorization: Bearer $TOKEN" \
  https://api.your-brand.com/cloud/subscription
# → {"plan":"free","quota":20,"remaining":20,"used":0,...}

# 消耗 1 次额度(免费额度 20 次/月)
for i in $(seq 1 20); do
  curl -s -X POST https://api.your-brand.com/cloud/usage/consume \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"amount":1}' > /dev/null
done

# 再试一次应返回 402(额度耗尽)
curl -X POST https://api.your-brand.com/cloud/usage/consume \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"amount":1}'
# → 402 {"detail":"quota exceeded: 21/20 in 2026-10"}
```

### 7.3 订阅(支付)

```bash
# 创建订单(plan=pro, days=30, ¥99)
ORDER=$(curl -s -X POST https://api.your-brand.com/cloud/payment/create_order \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"plan":"pro","days":30,"channel":"alipay"}')

echo "$ORDER" | jq
# → {"order_no":"PF20261013...","amount":99.00,"plan":"pro","days":30,
#    "channel":"alipay","pay_params":{"pay_type":"form","form_html":"<form ...>"}}

# 打开 pay_params.form_html 里的 form 提交(支付宝跳转)
# 或调微信 wechat 通道 → 得到 code_url,客户端渲染二维码

# 查询订单状态
curl -H "Authorization: Bearer $TOKEN" \
  https://api.your-brand.com/cloud/payment/order/PF20261013...
# → 初始: status="created";支付成功后: status="paid"
```

### 7.4 AI 走云端

```bash
# 调用云端 LLM(prompt 由云端渲染,LLM key 在云端)
curl -X POST https://api.your-brand.com/cloud/llm/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt_name":"cognition.matrix_evaluate","variables":{"content":"今天天气不错"}}'
# → {"ok":true,"prompt_name":"cognition.matrix_evaluate","content":"...LLM 结果...",
#    "usage_after":{"used":1,"remaining":19,"plan":"free"}}

# 列出可用 prompt(客户端 UI 展示用)
curl -H "Authorization: Bearer $TOKEN" \
  https://api.your-brand.com/cloud/llm/prompts
# → {"total":N,"items":[{"name":"...","variables":[...],"description":"..."}]}
```

### 7.5 离线降级验证

**方法 1**:直接改 DNS 让云端域名解析失败。

```bash
# 在客户端机器 hosts 文件加:
# 127.0.0.1 api.your-brand.com
# Windows: C:\Windows\System32\drivers\etc\hosts
# macOS/Linux: /etc/hosts
# 然后刷新 DNS 缓存
ipconfig /flushdns    # Windows
# 或 sudo dscacheutil -flushcache  # macOS
```

**方法 2**:临时停掉 cloud_service。

```bash
systemctl stop prism-cloud
```

**预期行为**:
1. 客户端 `cloud_gateway.verify_license()` 返回 `LicenseStatus(valid=False, reason="cloud_unreachable")`。
2. `prompt_router` 检测到 `cloud_reachable=False`,降级到 `basic tier`。
3. 用户在客户端能选**用户自配 LLM key**(如 OpenAI/DeepSeek/SiliconFlow)继续用。
4. 客户端**本地功能不受影响**:浏览器自动化、文件管理、账号同步、发布。

**方法 3**:直接调 `cloud_gateway.probe_cloud_reachable()`(单元测试级):

```python
from prism_backend.fusion_ai.cloud_gateway import get_gateway
gw = get_gateway(cloud_base_url="https://api.your-brand.com")
print(gw.probe_cloud_reachable())      # False
print(gw.verify_license())             # LicenseStatus(valid=False, reason="cloud_unreachable")
```

---

## 8. 故障排查

### 8.1 JWT secret 未配置

**症状**:重启服务后所有用户被踢下线;`/cloud/auth/login` 返回的 token 无法通过 `/cloud/auth/me` 校验。

**检查**:

```bash
# cloud_service/settings.py:90-94 会检测 secret 来源
source /opt/prism-fusion/venv/bin/activate
python -c "from cloud_service.settings import get_settings; s=get_settings(); print('source:', s['jwt_secret_source'])"
# → source: random-in-memory  ← 说明未配置!
```

**修复**:在 `.env.cloud` 加 `CLOUDJWT_SECRET=*** -c "import secrets; print(secrets.token_urlsafe(48))"` 后 `systemctl restart prism-cloud`。

### 8.2 DB 连不上

**症状**:`journalctl -u prism-cloud` 出现 `pymysql.err.OperationalError: (2003, "Can't connect to MySQL server on ...")`。

**排查步骤**:

```bash
# 1. 检查 RDS 白名单
mysql -h <rds-host> -u prism -p   # 应能连上
# 2. 从 ECS 内部测试连通性
nc -vz <rds-host> 3306
# 3. 检查账号密码
grep CLOUD_DB_URL /opt/prism-fusion/.env.cloud
# 4. 检查 systemd 是否正确加载环境变量
systemctl show prism-cloud | grep EnvironmentFile
journalctl -u prism-cloud -n 50
```

**常见原因**:
- RDS 白名单未加 ECS 内网 IP
- `.env.cloud` 里的密码有特殊字符未转义(建议 URL encode)
- ECS 无法访问 RDS 的 3306 端口(网络 ACL)
- 数据库名 / 账号不存在

### 8.3 云端不可达(客户端报 cloud_unreachable)

**症状**:客户端 `cloud_gateway.py` 日志出现 `GatewayError: cloud unreachable`。

**排查步骤**:

```bash
# 1. 云端侧
curl -v https://api.your-brand.com/health
# 2. Nginx 层
tail -50 /var/log/nginx/prism-cloud.error.log
# 3. cloud_service 层
journalctl -u prism-cloud -n 100
# 4. DNS 解析
nslookup api.your-brand.com
# 5. 端口连通
nc -vz api.your-brand.com 443
```

**常见原因**:
- 域名解析未生效(等 5-10 分钟)
- 备案未完成,ECS 80/443 未开放
- Nginx 未监听 443
- cloud_service 进程挂了(`systemctl status prism-cloud`)
- 客户端防火墙 / 代理拦截

### 8.4 支付回调失败

**症状**:用户完成支付,但订单状态仍是 `created`;支付宝/微信商户后台显示"通知失败"。

**排查步骤**:

```bash
# 1. Nginx 访问日志看回调请求
grep "/cloud/payment/callback" /var/log/nginx/prism-cloud.access.log | tail -20
# 2. cloud_service 日志
journalctl -u prism-cloud -n 100 | grep -i "payment\|callback"
# 3. 从公网测试回调 URL 可达性
curl -v https://api.your-brand.com/cloud/payment/callback/alipay -d '{}' -H "Content-Type: application/json"
# 4. 检查订单记录
mysql ... -e "SELECT * FROM orders WHERE order_no='PF...';"
```

**常见原因**:
- 回调 URL 未走 HTTPS(支付宝/微信强制要求)
- 回调 URL 未备案(微信强制)
- 回调验签失败(mock 阶段的 HMAC secret 与真实渠道密钥不一致)
- 回调处理时间超过 3s(支付宝要求 15s 内响应;微信要求 3-5s)
- 订单幂等检查失败(order_no 重复但 status 不一致)
- 金额不一致校验失败(`amount mismatch` 日志)

**⚠️ 生产前必须**将 `payment/alipay.py` 和 `payment/wechat.py` 从 mock 签名切换到官方 SDK 签名。

### 8.5 LLM key 缺失

**症状**:调用 `/cloud/llm/chat` 返回 `503 {"detail":"cloud LLM not configured (server-side)"}`。

**排查步骤**:

```bash
# 1. 检查 key 是否配置
curl https://api.your-brand.com/cloud/llm/health
# → {"api_key_configured":false,...}  ← key 未配

# 2. 检查环境变量
systemctl show prism-cloud | grep Environment
# 3. 测试 key 有效性(从 ECS 直接调)
source /opt/prism-fusion/venv/bin/activate
python -c "
import os, asyncio
from openai import AsyncOpenAI
async def test():
    c = AsyncOpenAI(api_key=os.environ['CLOUD_LLM_API_KEY'], base_url=os.environ['CLOUD_LLM_BASE_URL'])
    r = await c.chat.completions.create(model=os.environ['CLOUD_LLM_MODEL'], messages=[{'role':'user','content':'ping'}], max_tokens=5)
    print(r.choices[0].message.content)
asyncio.run(test())
"
```

**修复**:在 `.env.cloud` 设置 `CLOUD_LLM_API_KEY=<你的 API key>`,`systemctl restart prism-cloud`。

### 8.6 订阅过期未激活

**症状**:用户支付成功但订阅仍是 free 或已过期。

**排查**:

```bash
# 1. 订单状态
curl -H "Authorization: Bearer $TOKEN" \
  https://api.your-brand.com/cloud/payment/order/<order_no>
# 2. 订阅状态
curl -H "Authorization: Bearer $TOKEN" \
  https://api.your-brand.com/cloud/subscription
# 3. DB 直接查
mysql -e "SELECT * FROM subscriptions WHERE user_id=1;"
```

**常见原因**:
- 支付回调未成功(见 8.4)
- `billing.activate_for_user` 抛异常(检查 journalctl)
- 订单被多次回调导致状态错乱(检查 orders 表 paid_at 时间戳)

### 8.7 Nginx 502 Bad Gateway

**症状**:`curl https://api.your-brand.com/health` 返回 502。

**排查**:

```bash
# 1. cloud_service 是否在监听
ss -tlnp | grep 8000
# 2. systemd 服务状态
systemctl status prism-cloud
# 3. 手动启动测试
source /opt/prism-fusion/venv/bin/activate
cd /opt/prism-fusion/cloud_service
python -m uvicorn cloud_service.main:app --host 127.0.0.1 --port 8001
curl http://127.0.0.1:8001/health
```

**常见原因**:
- cloud_service 崩溃(检查 journalctl)
- 端口被占用
- systemd 服务未启动
- Nginx 配置 upstream 端口错误

### 8.8 systemd 加载 env 失败

**症状**:cloud_service 报"环境变量未配置"错误,但 `.env.cloud` 文件明明有值。

**排查**:

```bash
# 1. systemd 是否能读到文件
systemctl show prism-cloud --property=EnvironmentFiles
# 2. 用 systemd-analyze 排查
systemd-analyze verify /etc/systemd/system/prism-cloud.service
# 3. 直接运行验证
sudo bash -c 'set -a; source /opt/prism-fusion/.env.cloud; set +a; systemctl restart prism-cloud'
# 4. 检查 ExecStart 里 EnvironmentFile 语法
```

**常见原因**:
- `EnvironmentFile=` 路径写错或文件不可读(权限)
- env 文件有语法错误(空格、引号、`export` 前缀)
- 特殊字符未转义(推荐用单引号包 value)
- systemd unit 里缺少 `EnvironmentFile=` 行

---

## 9. 附录

### 9.1 常用运维命令

```bash
# 服务管理
systemctl status prism-cloud
systemctl restart prism-cloud
systemctl stop prism-cloud
journalctl -u prism-cloud -f                    # 实时日志
journalctl -u prism-cloud -n 200 --no-pager     # 最近 200 行

# 部署新代码
cd /opt/prism-fusion/cloud_service
git pull
source /opt/prism-fusion/venv/bin/activate
pip install --upgrade fastapi uvicorn sqlalchemy   # 按需
python -c "from cloud_service.db import init_db; init_db()"
systemctl restart prism-cloud

# Nginx
nginx -t
systemctl reload nginx
tail -f /var/log/nginx/prism-cloud.access.log
tail -f /var/log/nginx/prism-cloud.error.log

# 数据库
mysql -h <rds-host> -u prism -p prism_cloud

# 证书续期
certbot renew --dry-run
systemctl list-timers | grep certbot
```

### 9.2 API 端点清单

cloud_service 挂载点在 `cloud_service/main.py:43-48`:

| 前缀 | 模块 | 用途 |
|---|---|---|
| `/health` | 主入口 | 存活探针 |
| `/cloud/auth/*` | `auth/router.py` | register / login / refresh / me |
| `/cloud/subscription` | `billing/router.py` | 当前订阅 |
| `/cloud/usage/*` | `billing/router.py` | 额度消耗/查询 |
| `/cloud/license/*` | `billing/router.py` | 客户端 license 校验 |
| `/cloud/llm/chat` | `llm_proxy/router.py` | LLM 代理 |
| `/cloud/llm/prompts` | `llm_proxy/router.py` | 列出可用 prompt |
| `/cloud/llm/health` | `llm_proxy/router.py` | LLM 探针(无 JWT) |
| `/cloud/prompts-export` | `llm_proxy/router.py` | 离线版 prompt 导出(需 X-Admin-Token) |
| `/cloud/payment/*` | `payment/router.py` | create_order / callback / order 查询 |

### 9.3 客户端环境变量速查

| 变量 | 位置 | 用途 | 生产值示例 |
|---|---|---|---|
| `LAOMA_CLOUD_BASE_URL` | 后端 Python | 云端根 URL(不带 `/cloud`) | `https://api.your-brand.com` |
| `NEXT_PUBLIC_CLOUD_URL` | 前端 build-time | 浏览器端云端 URL | `https://api.your-brand.com` |
| `NEXT_PUBLIC_BACKEND_URL` | 前端 build-time | 本地后端 URL | `http://127.0.0.1:7000` |
| `LAOMA_INTERNAL_BACKEND_URL` | 前端 server-side | 容器内后端 URL | `http://app:7000` |
| `ELECTRON_SAFE_STORAGE` | Electron 主进程 | 启用系统加密存储 | `1` |

### 9.4 客户端打包产物发布

- **Windows 安装包**:`desktop-electron/dist-out/vN/老马AI工作台-x.x.x-setup.exe`
- **发布渠道**:
  - GitHub Releases(免费,自动 electron-updater)
  - OSS/COS 静态站点托管(推荐 + CDN)
- **自动更新**:`electron-updater` 已配置(`desktop-electron/package.json`),发布时更新 `electron-builder.yml` 的 publish 配置。

### 9.5 参考资料

- 设计文档:`docs/dev-reports/2026-10-13-saas-c-class-design.md`(第 5 章部署方案)
- 计划文档:`_plan_productization_saas.md`(C20 云资源、C21 部署脚本)
- 客户端双通道:`prism_backend/fusion_ai/cloud_gateway.py`
- 前端环境变量:`prism_frontend/src/lib/env.ts`
- 打包脚本:`scripts/packaging/build-package.bat`
- Nginx 模板:`scripts/deploy/nginx.conf`

---

## 10. 已知待办与不确定性

以下项在本指南中**假设或标注**,执行 agent 需要在实际部署时确认:

1. **支付真实接入**:当前 `payment/alipay.py` / `payment/wechat.py` 是 mock 签名(HMAC-SHA256),生产前必须替换为官方 SDK(RSA2 / AES-256-GCM)。
2. **客户端证书校验**:客户端默认信任系统 CA;若使用自建 CA 需额外配置。
3. **HTTPS 端口冲突**:若 Nginx 已用于其他服务,需按 domain 或 IP 分配端口。
4. **备份策略**:RDS 默认自动备份,但需确认周期和保留天数(建议至少 7 天)。
5. **DDoS 防护**:高流量场景需接入云商 DDoS 高防,当前指南未覆盖。
6. **多可用区/多地域**:单点部署,ECS 故障时服务不可用。生产上建议至少 2 个可用区 + SLB。
7. **日志与监控**:当前依赖 `journalctl`,未接入 ELK / Prometheus + Grafana;生产建议引入。
8. **限流**:cloud_service 当前未做 API 限流(依赖 Nginx 或上游云商);建议加 `redis` + 令牌桶。
9. **审计日志**:关键操作(注册/登录/支付回调)未做集中审计;建议落 SLS(阿里云)/CLS(腾讯云)。
10. **多租户隔离**:当前是单租户部署;若面向多客户,需按租户分库或分区。
