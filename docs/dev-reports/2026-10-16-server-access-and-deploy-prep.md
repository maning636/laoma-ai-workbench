# 服务器访问与部署准备(2026-10-16)

> 读者:后续执行部署的 agent / 开发负责人
> 范围:SSH 免密访问、MariaDB 就绪状态、服务器环境实况、部署前置待办
> **本文档不含任何密码、私钥或密钥内容**(这些分别在本地 `_deploy_inputs/ssh/` 与服务器 root-only 文件里)

---

## 1. SSH 免密访问(2026-10-16 建立)

### 1.1 密钥

| 项 | 值 |
|---|---|
| 类型 | Ed25519 |
| 私钥(本地,**不提交**) | `D:\dim开发\Prism-Fusion\_deploy_inputs\ssh\prism_deploy_ed25519` |
| 公钥(本地) | 同目录 `prism_deploy_ed25519.pub`(注释 `prism-fusion-deploy`) |
| 公钥落点 | 服务器 `/root/.ssh/authorized_keys`(`/root/.ssh` 700、文件 600) |
| 验证结果 | ✅ 用私钥登录成功:`whoami=root`、`hostname=VM-0-10-opencloudos` |

`_deploy_inputs/` 已被 `.gitignore` 遮蔽(见仓库 `.gitignore` 的 `_deploy_inputs/` 规则),**私钥不会进版本库**。

### 1.2 怎么用

**命令行(Windows OpenSSH)**
```powershell
ssh -i 'D:\dim开发\Prism-Fusion\_deploy_inputs\ssh\prism_deploy_ed25519' root@101.43.65.216
scp -i 'D:\dim开发\Prism-Fusion\_deploy_inputs\ssh\prism_deploy_ed25519' <本地文件> root@101.43.65.216:/opt/prism-fusion/
```

**Python(paramiko,子代理自动化推荐)**
```python
import paramiko
key = paramiko.Ed25519Key.from_private_key_file(
    r"D:\dim开发\Prism-Fusion\_deploy_inputs\ssh\prism_deploy_ed25519"
)
cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect("101.43.65.216", 22, "root", pkey=key, timeout=20,
            allow_agent=False, look_for_keys=False)
```
> `paramiko` 已装进 `prismenv`(本地运维用,**未**加入 `requirements.txt`)。

### 1.3 安全约定

- **密码登录仍然开启**(没有削弱原有认证),密钥只是新增一种方式;若日后要关闭密码登录,需先确认另一台机器(Kimi 那边)已改用密钥。
- 服务器密码已于 2026-10-16 更换,新密码**只存在于会话与服务器**,不落任何文件。
- **不要把私钥复制到 C 盘**(`~/.ssh` 在 C 盘 —— 本项目的硬约束是"不往 C 盘写东西")。
- 不要把私钥内容贴进对话/文档/提交。

---

## 2. 服务器实况(2026-10-16 实测)

| 项 | 值 |
|---|---|
| IP / 主机名 | `101.43.65.216` / `VM-0-10-opencloudos` |
| 系统 | **OpenCloudOS 9.6**(RHEL 系,**用 `dnf`/`yum`,不要写 `apt`**) |
| CPU / 内存 | 4 核 / 3.6 Gi(可用约 **2.8 Gi**) |
| 磁盘 | 40 G,已用 7.6 G,**剩 33 G** |
| nginx | **1.29.8**,监听 `0.0.0.0:80` + `0.0.0.0:443`;站点配置 `/etc/nginx/conf.d/fde.conf`(另有多个 `.bak.*`) |
| 现有服务 | `127.0.0.1:8090` payskill-server、`127.0.0.1:8787` python3(Pay Skill 相关) |
| firewalld | **inactive**(未启用本机防火墙 → 端口暴露与否**取决于腾讯云安全组**) |
| Python | **3.11.6**,⚠️ **`pip` 未安装**(`python3 -m pip` → `No module named pip`) |
| 对外端口 | 仅 80/443(nginx 统一入口),其余服务一律绑 `127.0.0.1` |

### 部署影响

1. **端口规划**:新服务不要新开公网端口,绑 `127.0.0.1:8091`(cloud_service)之类,由 nginx 反代。
2. **Python 3.11.6**:低于部署指南假设的 ≥3.12。好消息:CI 用的就是 3.11,且 `cloud_service/**/*.py` 已静态核验语法兼容 3.11。**但仍需真机实测**。
3. **缺 pip**:部署第一步要 `dnf install -y python3-pip`(或 `python3 -m ensurepip`),否则装不了依赖、建不了 venv。
4. **内存 2.8 Gi 可用**,且与 Pay Skill 共用 → cloud_service 的 uvicorn **不要超过 2 worker**;前端建议**本地构建后只传产物**。

---

## 3. MariaDB(2026-10-16 安装就绪)

| 项 | 值 |
|---|---|
| 版本 | **MariaDB 10.11.18**(`mariadb-server-10.11.18-1.oc9`) |
| 状态 | `systemctl is-active mariadb` → **active**,已 `enable` 开机自启 |
| 监听 | **`127.0.0.1:3306`**(仅回环) |
| 配置文件 | `/etc/my.cnf.d/zz-prism.cnf` |
| 数据库 | `prism_cloud`(utf8mb4 / utf8mb4_unicode_ci) |
| 应用用户 | `prism@127.0.0.1` |
| 凭据文件 | `/opt/prism-fusion/.db_credentials`(目录 700 / 文件 **600**,含 `CLOUD_DB_URL`) |
| 连通性 | ✅ 用凭据文件内的账号密码 `SELECT 1` → `ok / 1` |

**调优参数(为 3.6 G 小机器)**:
```ini
[mysqld]
innodb_buffer_pool_size = 128M
innodb_log_file_size = 48M
max_connections = 50
character-set-server = utf8mb4
collation-server = utf8mb4_unicode_ci
bind-address = 127.0.0.1
```
常驻内存实测约 **90 MB**(装完前后 `used` 从 754 M → 836 M)。

### ⚠️ 安装过程中发现并已修复的问题

初次安装后 MariaDB **默认监听 `0.0.0.0:3306`**(对外暴露,若安全组放行 3306 即等于数据库挂在公网)。已通过 `bind-address = 127.0.0.1` 收敛并重启验证。
**建议顺带检查腾讯云安全组:3306 / 8090 / 8787 一律不应对外开放。**

### 后续连接串

应用侧只需读服务器上的凭据文件,不用手抄密码:
```
CLOUD_DB_URL=mysql+pymysql://prism:<password>@127.0.0.1:3306/prism_cloud?charset=utf8mb4
```
> `cloud_service` 用 SQLAlchemy,新增驱动依赖 **`pymysql`**(服务器上当前未装)。

---

## 4. 部署前置待办(按顺序)

| # | 待办 | 说明 |
|---|---|---|
| 1 | `dnf install -y python3-pip` | 服务器缺 pip,否则无法装依赖 |
| 2 | 建 venv + 装依赖 | `python3 -m venv /opt/prism-fusion/venv`,装 fastapi/uvicorn/sqlalchemy/pymysql/pyjwt/bcrypt/httpx/openai/loguru |
| 3 | 传代码 | 两条路:① `git clone`(需远程仓库,**尚未 push**);② 用密钥 `scp/rsync` 直传 `cloud_service/` |
| 4 | 写 `.env.cloud` | 至少要 `CLOUDJWT_SECRET`(现场生成)、`CLOUD_DB_URL`(读 `.db_credentials`)、`CLOUD_LLM_*`(**待用户给 key**)、`CLOUD_CORS_ORIGINS`(子域名) |
| 5 | systemd unit + nginx 反代 | 新配置放 `/etc/nginx/conf.d/`,**不要动 `fde.conf`**(Pay Skill 在用) |
| 6 | 子域名 DNS + 证书 | 用户已定"给项目单独子域名";需新增解析,并确认证书覆盖该子域名 |
| 7 | 支付真实对接 | 微信:参考 Pay Skill 已验证实现(**其代码在另一台机器,本机读不到**);支付宝:商户号未申请 |
| 8 | 真机联调 | 注册 → 登录 → 订阅 → 调 AI(全链路) |

---

## 5. 未完成 / 需用户提供

- **云端 LLM API key**(`CLOUD_LLM_API_KEY`,建议 DeepSeek)—— 没有它,AI 链路只能在真机上报 503。
- **代码落地方式**:远程仓库地址(或确认走 scp 直传)。
- **支付宝商户号**:未申请(周期 2–3 周)。
- **Pay Skill 微信实现的可读副本**:若要走"复用"路线,需把相关代码/配置复制到本机(或明确改为按微信官方 APIv3 文档实现)。
