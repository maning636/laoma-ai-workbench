# Prism-Fusion 剩余开发工作清单(不含 API/外部依赖部分)

> 生成时间:2026-10-15
> 范围:阶段 A(P0-P5)与阶段 B 主体、C 类 SaaS 主体均已落地并入库(本地 14 个 commit)。
> 本文只列**还没做、且不依赖外部 API/凭据/云资源就能推进**的开发工作。
> **需外部输入的部分(真实支付对接、上游 key、云资源、真机联调)统一放在 §6,不混入主线。**
> 状态来源:`docs/dev-reports/2026-10-13-project-handover.md` §6.6 待复核清单(权威)+ 2026-10-15 的实测核对。
> 工时口径:纯开发工时粗估,实际日历周期 ×1.5~2;不含沟通/决策/调试反复。

---

## 1. 前端(共 ~6-7.5 人日)

| # | 任务 | 要点 | 涉及文件 | 验收 | 依赖 | 粗估 |
|---|---|---|---|---|---|---|
| F-A | **流式通道接入调用方** | 后端 `/cloud/llm/stream` 与前端 `gatewayStream()` 已就绪,但 UI 仍走非流式 | `prism_frontend/src/hooks/useAgentStream.ts`、`useHermesStream.ts`、`app/ai-agent/`、`components/hermes-chat/`、`prism_backend/fusion_ai/{cloud_gateway,router}.py` | 聊天界面出现逐字输出;失败可回落非流式 | 无 | 1-1.5d |
| F-B | **前端测试基建 + 网关单测** | 目前 `prism_frontend` **无测试目录**;流式解析仅靠 Node 探针验证过 | 新建 vitest 配置;测 `client-gateway.ts`(401/402/5xx/network)、`parseSSEStream`(半帧跨 chunk、UTF-8 多字节边界、`[DONE]`)、`gatewayStream`(onDone 恰好一次) | `npm run test` 全绿;覆盖上述分支 | 无 | 1-1.5d |
| F-C | **清理 23 条历史 tsc 错误** | 实测 `npx tsc --noEmit` 仍报 23 条,全部与 SaaS 改动无关 | `HermesChatPage.tsx`、`useHermesStream.ts`、`breakdown/`、`calendar/`、`moderation/`、`skills/`、`ai-agent-chat.tsx`、`navbar-new.tsx`、`sidebar-new.tsx`、`breadcrumb.tsx` | tsc 归零(或降到明确白名单) | 无 | 1-1.5d |
| F-D | **license 离线误判策略** | 网络抖动时不得把有效订阅判失效;当前前端不缓存 license,靠 24h 心跳 | `prism_frontend/src/hooks/useLicenseHeartbeat.ts`、`lib/cloud-auth.ts` | 模拟抖动不出现"订阅失效";有单测 | 无 | 0.5-1d |
| F-E | **网关抽象对称化** | 后端是 `CloudGateway` 类 + 单例,前端是纯函数;`probe_cloud_reachable` / `build_tier_context` 前端未封装 | `prism_frontend/src/lib/client-gateway.ts` | 客户端 prompt 路由可复用同一入口 | 无 | 1d |
| F-F | **小项合集** | ① F7 心跳单位换算边界(`"999"`=999s, `"1000"`=1s)统一成带单位写法;② F8 `feature` 白名单未被使用;③ F11 usage 缺失时字符估算偏差标注 | `useLicenseHeartbeat.ts`、`client-gateway.ts`、`.env.local.example` | 三项各有说明或修复 | 无 | 0.5d |
| F-G | **流式中断的计费缺口** | 客户端 AbortController / 断网 → `GeneratorExit` 绕过异常分支,**内容已发但未扣额度** | `cloud_service/llm_proxy/router.py`(预消费+回滚)、`client-gateway.ts` | 中断场景额度被正确扣减或回滚;有测试 | 无 | 1d |

---

## 2. 云端 cloud_service(共 ~4.5-6 人日,不含需外部 key 的验证)

| # | 任务 | 要点 | 涉及文件 | 验收 | 依赖 | 粗估 |
|---|---|---|---|---|---|---|
| C-A | **补 CORS 中间件** | 实测 `cloud_service/main.py` **无 CORSMiddleware**,浏览器跨源直连会被拒(演示/本地联调需要) | `cloud_service/main.py` | 浏览器直连 8000 成功;`allow_credentials=False`(前端 `credentials:"omit"`) | 无 | 0.2d |
| C-B | **补 `.env.example`** | `cloud_service/` 下不存在该文件,今天新增的 6 个 env(`CLOUD_ORDER_TIMEOUT_*` / `CLOUD_RECONCILE_*`)无处记录 | 新建 `cloud_service/.env.example` | 与 `settings.py` 字段逐条对齐 | 无 | 0.2d |
| C-C | **补 cloud_service 启动器** | `scripts/launchers/` 里没有 cloud 相关 bat(backend/frontend/celery 都有) | 新建 `scripts/launchers/start_cloud_prismenv.bat` | 一键起 8000(SQLite) | 无 | 0.3d |
| C-D | **多 worker 任务去重** | `--workers>1` 时每个 worker 各跑一份超时/对账任务;对账会**重复调商户账单接口** | `cloud_service/main.py`、`payment/scheduler.py`;或改独立进程/RQ 锁 | 多 worker 下只有一个实例执行 | 无(Redis 锁方案需 Redis) | 1d |
| C-E | **对账单次超时保护** | `reconcile_task` 无 `wait_for`,adapter 卡住会推后下一轮 | `cloud_service/payment/reconciliation.py` | 单次执行有 timeout + 退避 | 无 | 0.5d |
| C-F | **退款↔订阅语义** | `billing` 只有"延长"语义;退款当前不撤销订阅;部分退款无独立状态 | `cloud_service/billing/`、`payment/router.py`、`models.py` | 有明确接口(`cancel_subscription` / `shorten_subscription`)或明确不改 | **需业务规则决策**(见 §6) | 1-1.5d |
| C-G | **C16a Hermes 双通道真机联调** | 骨架已建(订阅态写代理 endpoint),**真机联调未跑** | `prism_backend/fastapi_app/agent/hermes_config.py`、`fusion_ai/cloud_gateway.py` | 订阅态 Hermes 经代理调 LLM 成功;离线态不受影响 | 可先用本地 cloud_service 代替真机 | 1-1.5d |
| C-H | **C18 加固范围扩展** | 目前只混淆 `cloud_gateway.py` 一个模块 | `scripts/packaging/obfuscate.py`、`build_services.ps1`;目标:token 校验 / 订阅心跳 / 双版本判定 | 打包产物可运行且被混淆 | **需 pyarmor 商业版 license** | 2-3d |

---

## 3. 本地后端 prism_backend(共 ~1.5-2 人日)

| # | 任务 | 要点 | 涉及文件 | 验收 | 依赖 | 粗估 |
|---|---|---|---|---|---|---|
| B-A | **B7 残余收尾** | SERVICE_REGISTRY 主结构已落地,遗留:`api_server.py` 的 `/status` 列表未切 registry、`get_service_launch`/env name 分支保留、`stop_order` 语义未真机回归 | `desktop-electron/resources/supervisor/supervisor.py`、`prism_backend/.../api_server.py` | `/status` 读 registry;stop_order 真机验证 | 无 | 0.5-1d |
| B-B | **启动残余优化** | B10 已从 26s → 2-3s,仍有约 2s Hermes 冷启动 | `prism_backend/fastapi_app/agent/hermes_*.py` | 冷启动 ≤2s 或明确记录不可优化原因 | 无 | 0.5d |
| B-C | **C17 key 剥离路径回归** | 订阅态清空三处本地 key 的逻辑缺针对性测试 | `prism_backend/fastapi_app/core/config.py`、`ai/router.py`、`agent/hermes_config.py` | 订阅↔离线切换各有测试;离线态 key 不被误清 | 无 | 0.5d |

---

## 4. 工程 / CI / 打包(共 ~2.5-3 人日)

| # | 任务 | 要点 | 涉及文件 | 验收 | 依赖 | 粗估 |
|---|---|---|---|---|---|---|
| E-A | **C21 部署产物** | 仓库里**没有** Dockerfile / Nginx 配置 / systemd unit / 部署脚本 / CI-CD;现只有 1174 行手工命令级指南 | 新建 `deploy/`(Dockerfile、nginx.conf、prism-cloud.service、部署脚本)、`.github/workflows/deploy.yml` | 产物齐备;**在真实服务器上验证需云环境**(见 §6) | 无(编写不依赖外部) | 1-1.5d |
| E-B | **Python 版本收敛** | 本地 `prismenv` **3.13.14** / CI 四个 job **3.11** / 部署目标 Ubuntu 自带 **3.10-3.12**;已静态核验 `cloud_service/**/*.py` 语法兼容 3.11,运行时差异未验证 | `requirements-dev.txt`、`.github/workflows/ci.yml`、`STARTUP.md`、`PACKAGING.md` | 三处版本口径统一并写入文档 | 无 | 0.5d |
| E-C | **打包 e2e 回归** | 打包链路改动后需复跑烟测(上次实测 14m46s,产物 1797MB) | `scripts/tests/e2e_packaged_test.ps1`、`integration_test.py` | 中文/空格路径下可启动、API 全绿 | 无 | 0.5d |
| E-D | **提交/推送收口** | 本地已累积 14 个 commit **未 push**;早期 14 个新 API 目录与 `api/v1/router.py` 分散在不同 commit,**必须一次性 push** | — | 远程仓库与本地一致 | **需远程仓库地址/凭据**(见 §6) | 0.2d |
| E-E | ✅ **Celery 连不上 Redis —— 已于 2026-10-15 修复** | 根因:`prismenv` 的 `redis-py 8.1.0` 默认走 RESP3(握手发 `HELLO 3`),而仓库内置 `desktop-electron\resources\redis\redis-server.exe` 是 **Redis 5.0.14**(不支持 `HELLO`)→ 永远连不上 broker。**采用修法③**:降级 `redis-py` 到 **4.6.0** + `requirements.txt` 把 `redis` 改为 **`redis<5`**(附原因注释)。验证:`redis.Redis().ping()` → `True`;`celery inspect ping` → **`pong`**(`prism-worker-test@DESKTOP-HOT7UMB`,1 node online);日志无 `unknown command 'HELLO'`;后端/前端仍 200 | `requirements.txt`(已改,未提交) | — | ✅ 完成 |
| E-E3 | **Celery 消费链路无害验证(缺口)** | 2026-10-15 实测:`inspect ping` → `pong`、`inspect registered` → 任务已注册、worker `ready.`(PID 6408+13168),但**"能消费任务"这一项没验成** —— 仓库里只有 `publish.single` / `publish.batch` 两个**真实发布任务**,没有无害探针,不能拿它冒险 | 在 `prism_backend/fastapi_app/tasks/` 加一个 `@shared_task` 的 echo/ping(2 行),然后投递一次并确认被消费;补进测试 | 0.2d |
| E-E2 | **打包回归(因 redis 版本变更而升级为必做)** | `redis-py` 8.1.0 → 4.6.0 会改变 PyInstaller 产物内的依赖;需确认打包后 Celery 仍能连内置 Redis | `scripts/tests/e2e_packaged_test.ps1`、`integration_test.py` | 打包产物启动正常 + Celery 可连 | 无 | 0.5d(含 15min 打包) |

---

## 5. 长期 review 小项(D 类,共 ~1-2 人日,零散穿插)

- 6 模块前缀兼容层(`/api/v1/api/v1/`)观察期后移除
- Easel `openclaw.json` 目录备份(目前只备份文件,不足)
- `openclaw@latest` pin 版本
- `paths.json` 加入 `.gitignore`(防误追踪)
- health-check fast/full 分档完善
- `automation_worker` 日志统一到 `data/logs`
- 跨会话计划编号口径统一(避免 P0-P7 定义混乱)
- hermes `get_update_status` 回滚字段(已做,复核确认)
- `cloud_service/test_*.py` 与 CI 的长期维护约定(新增脚本自动被 `conftest.py` 收集)

---

## 6. 暂缓:需要外部输入(不在本文主线内)

| 项 | 卡在哪 | 一旦输入到位即可开工 |
|---|---|---|
| **真实上游 LLM key** | 用户稍后提供(放 `_deploy_inputs/`,勿粘聊天) | 写入 `ai_model_configs` 或 `.env`,跑一次真实请求验证 |
| **支付真实对接** | 需要支付宝/微信商户参数;当前适配器是 **mock/HMAC 模拟签名**,全目录 `httpx`/官方 SDK 0 命中 | 支付宝电脑网站支付、微信 Native/JSAPI、官方验签、退款、账单下载(约 3-5 人日) |
| **支付宝商户号** | 未申请(微信已注册,但 mch_id / APIv3 密钥 / API 证书待确认) | 申请后即可接真实支付 |
| **C20 云资源** | 备案 ✅ / 域名解析 ✅ / HTTPS 证书 ✅;**ECS 实例、RDS MySQL 未确认** | 部署 cloud_service 并做真机联调 |
| **真机联调** | 依赖云环境 | 客户端 → 云端 → LLM → 支付全链路 |
| **P5 老库缺列** | 上线动作,非开发工作 | `ALTER TABLE orders ADD COLUMN refunded_at DATETIME`(仅对已存在的老库;新库 `init_db()` 自动建全列) |
| **C-F 的业务规则** | "退款是否撤销订阅""部分退款算不算独立状态"需业务侧拍板 | 拍板后 1-1.5d 落地 |
| **部署后更换服务器 root 密码** | 用户已指示"部署完事之后"更换(新密码在会话中给出,**不落盘、不进仓库、不写进任何脚本**) | 通过 SSH 执行 `passwd`;⚠️ 改密码**不能**解决"密码登录无法非交互自动化"的问题,建议同期配置 SSH 密钥对 |

---

## 7. 建议推进顺序(不含 §6)

1. **E-E 修复 Celery**(0.3-0.5d,真缺陷,异步任务依赖它;一行改动级修复但要验证透传)
2. **C-A / C-B / C-C**(0.7d,打地基,让云端能在本地一键起 + 浏览器直连)
3. **F-B 前端测试基建**(1-1.5d,后面所有前端改动都靠它兜底)
4. **F-A 流式接入调用方**(1-1.5d,用户可见体验提升最明显)
5. **C-D / C-E**(1.5d,把今天刚加的调度逻辑补稳,避免多 worker 隐患)
6. **B-A / B-C**(1-1.5d,本地后端收尾)
7. **F-C 清 tsc 存量**(1-1.5d,独立批次,不与功能改动混提)
8. **E-A / E-B**(1.5-2d,部署产物 + 版本口径,为真机联调铺路)
9. **C-G / F-D / F-E / F-F / F-G**(按需穿插)
10. **C-H**(需 pyarmor 商业版,放最后)

**不含 §6 的合计:约 17-22 人日**(含 E-E)。

---

## 附:本轮环境复核记录(2026-10-15)

| 服务 | 端口 | 状态 | 备注 |
|---|---|---|---|
| Redis | 6379 | ✅ | 版本 **5.0.14.1** —— 正是 E-E 的根因组件 |
| FastAPI Backend | 7000 | ✅ | `python fastapi_app/run.py` |
| Automation Worker | 7001 | ✅ | `automation_worker/worker.py` |
| React Frontend | 3000 | ✅ | next dev |
| Celery Worker | — | ❌ | 见 E-E(redis-py 8 RESP3 vs Redis 5) |
| Hermes Dashboard | 9119 | ❌ 未起 | 后端**不再自动拉起**(`prism_backend/fastapi_app/main.py` 注释);由 desktop Supervisor 托管,或用户 `POST /api/v1/agent/config/hermes/dashboard/start` 触发 |
| Persona API / Dashboard | 8787 / 5175 | ⏭️ 跳过 | `tools/persona-studio/` 目录**为空**、无 `persona` 模块、无 node_modules |
| C 盘污染 | — | ✅ 干净 | `Roaming`/`Local` 下今日无 `laoma|prism|electron` 相关新目录 |
