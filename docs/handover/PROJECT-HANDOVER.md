# 老马AI工作台（Prism-Fusion）· 项目全过程与交付清单

> **交接对象**：接手开发的工作组（AI Agent / 工程师均可）
> **交接日期**：2026-10-24
> **代码基线**：`c24a11d`（`6af4768` 之后追加了交接文档提交）
> **已发布版本**：GitHub Release `v1.1.5`
> **对外口径唯一权威**：[`docs/release-delivery-statement.md`](../release-delivery-statement.md)

---

## 0 怎么用这份文档（5 分钟上手）

### 0.1 这份文档解决什么问题

仓库里已经有一整套文档（`HANDOFF.md` 技术交接、`DEVELOPMENT-RECORD.md` 功能详录、`docs/PROJECT_OVERVIEW.md` 项目总览、`docs/dev-reports/` 43 份实施报告）。但它们有一个共同缺口：

> **`docs/dev-reports/` 43 份报告里，40 份写在 2026-10-16 之前。**
> 2026-10-17 至 2026-10-24 这 8 天的收官过程——合并为单一客户端、1.1.1→1.1.5 五个版本迭代、开源发布、CI 从软门全改硬门、开源发布待决表 7 项决策全部落地、备份 round18、41 项客户端验收清单——**没有任何一份连续记录**。

这份文档就是补上这一段，同时充当整个项目的**交棒入口**：告诉你交付了什么、怎么验证的、还差什么、接下来做什么、别踩哪些坑。

### 0.2 三条阅读路线

| 你是 | 必读 | 可跳 |
|---|---|---|
| 只运维 / 值班 | §2 交付清单 · §5 现状快照 · §9 操作手册 | §3 全过程 · §8 坑 |
| 要改代码 | 全部，尤其 §3 §4 §7 §8 §9 | — |
| 全面接手 / 项目负责人 | 全部，另加 §6 未来计划 | — |

### 0.3 术语速查

| 术语 | 含义 |
|---|---|
| **Prism-Fusion / 老马AI工作台 / LaomaAI-Fusion** | 同一个项目的前三种叫法。`Prism-Fusion` 是代码库名，`老马AI工作台` 是产品名（2026-10-13 从 `PRISM_` 品牌切换过来），`LaomaAI-Fusion` 是部分历史文档里的旧称 |
| **Community / Pro** | 商业分层。**现在是单一安装包**，客户端内按注册码与云端订阅的交集切换「完整版 / 限制功能版」。原先独立的 Community 安装包已于 2026-10-23 删除 |
| **注册码** | Ed25519 私钥签发、客户端离线验签的授权凭据。**本地注册码决定功能档位** |
| **feature gate / flag** | 云端订阅下发的功能开关（`max_accounts` / `max_platforms` / `agent_quota` 等 12 项）。真源见 `docs/feature-gate-matrix.md` |
| **判档模型** | **本地注册码 ∩ 云端订阅** → 派生最终档位。两边都满足才是「完整版」 |
| **cloud_service** | 云端服务（FastAPI + uvicorn，服务器 8091）。管注册/登录/计费/注册码/LLM 代理/feature gate |
| **prism_backend** | 本地后端（FastAPI + Celery + patchright）。管账号/素材/发布/数据回收/AI 生图 |
| **prism_frontend** | 前端（Next.js 16 App Router + React 19） |
| **desktop-electron** | Electron 壳 + Supervisor（拉起 4 个本地后端子进程）+ electron-builder 打包 |
| **asar** | Electron 应用包。解包后才能看到安装包内真实的代码与 package.json |
| **P1–P7 / D1–D5** | 两张待决表的编号。P = 开源发布收尾待决表，D = 客户端发布形态待决表。均已拍板落地 |
| **round18 / round19** | 备份目录的版本轮次。当前是 round18 |

### 0.4 证据分级（本文档通用约定）

| 标记 | 含义 |
|---|---|
| **【已验证】** | 2026-10-23/24 本轮实际执行命令或 HTTP 请求验证过，文中附了复核命令 |
| **【已确认】** | 马哥拍板或既有文档明确记载，不是我推测 |
| **【推测】** | 基于代码结构合理推断，**未实测**。接手后请自行复核，不要当事实用 |

---

## 1 项目是什么

### 1.1 一句话

**AI 驱动的社媒矩阵投放闭环桌面工作台** —— 覆盖「投-管-回-编」四环节：素材投放、账号管理、数据回收、AI 编辑与生成。

### 1.2 业务闭环

```
素材生产(AI生图/视频流水线)
    ↓
账号矩阵(扫码登录/Cookie/Persona指纹隔离)
    ↓
批量发布(多平台 × 多账号 × 定时)
    ↓
数据回收(播放/涨粉/转化 → 复盘输入)
    ↺ 回到选题与内容生产
```

### 1.3 支持平台（以后端发布通道为准，【已验证】）

前端向导 `prism_frontend/src/components/wizard/scenarios.tsx:231` 列了 8 个平台，但**后端真正有发布工具的只有 8 个，两边不是同一组**：

| 平台 | 后端发布工具 | 登录适配器 | 前端向导列出 |
|---|:---:|:---:|:---:|
| 抖音 douyin | ✅ | ✅ | ✅ |
| 快手 kuaishou | ✅ | ✅ | ✅ |
| 小红书 xiaohongshu | ✅ | ✅ | ✅ |
| B 站 bilibili | ✅ | ✅ | ✅ |
| 视频号 channels | ✅ | ✅ | ✅ |
| 百家号 baijiahao | ✅ | ❌ | ❌ |
| TikTok | ✅ | ❌ | ❌ |
| YouTube | ✅ | ❌ | ❌ |
| **知乎 / 头条 / 西瓜** | ❌ | ❌ | ✅ ⚠️ |

> ⚠️ **知乎/头条/西瓜在向导里能选，但后端没有发布通道** —— 走到发布这步会失败。这三者在后端只有 `fusion_ai/platform_styles.py`、`config_center.py`、`hot_topics.py` 里的**文案/风格**支持，不是发布通道。
> 后端发布工具集合见 `prism_backend/fastapi_app/services/publish_tools/_PLATFORM_MODULES`（`__init__.py:20`）；登录适配器见 `prism_backend/app_new/platforms/__init__.py`。
> **这是 §7 已知缺口里的第 1 条，建议优先修。**

### 1.4 商业模型（2026-10-23 拍板后定型）

| 环节 | 口径 |
|---|---|
| 支付 | **平台支付已彻底删除**（支付宝/微信支付代码全删）。收款走**个人微信 → 人工发注册码** |
| 判档 | 本地注册码 **∩** 云端订阅 |
| 分档体现 | 同一安装包内就地切换，激活后不用重装 |
| 自动更新 | 走 **generic provider** → `https://maning789link.top/downloads`，**不查 GitHub**（P3=A，理由见 §4） |
| 联系方式 | 官网**只放个人微信二维码**，不公开微信号文字（P5=B，防爬号批量加好友） |
| 云端 AI / TikHub | 平台密钥未配置时**隐藏入口 + 后端回中文「未配置」**提示（P7=B）。订阅与账号体系保留 |

---

## 2 交付清单（一屏看完）

### 2.1 对外可交付（终端用户能拿到的东西）

| # | 交付物 | 状态 | 地址 / 位置 | 验证方式 |
|---|---|:---:|---|---|
| 1 | 公开 GitHub 仓库 | ✅ | `https://github.com/maning636/laoma-ai-workbench` | 网页可访问；AGPL-3.0；1439 个跟踪文件 |
| 2 | Release `v1.1.5` | ✅ | `/releases/tag/v1.1.5`（id 421472164） | 3 个资产齐全 |
| 3 | 安装包 | ✅ | `LaomaAI-1.1.5-setup.exe`，**639,437,816 B**（≈610 MiB） | `Get-FileHash -Algorithm SHA512` |
| 4 | 安装包 SHA-256 | ✅ | `e99fb5bf…4baad19` | 与 `.blockmap`/`latest.yml` 三方对账 |
| 5 | 增量更新元数据 | ✅ | `LaomaAI-1.1.5-setup.exe.blockmap`（650,420 B）+ `latest.yml`（347 B） | `latest.yml` 内 `size: 639437816` 与磁盘一致 |
| 6 | 官网下载入口 | ✅ | `https://maning789link.top` | 首页 3 个下载链接（GitHub 直链为主 + 自建镜像兜底 + Release 页）全部 200 |
| 7 | 国内镜像下载 | ✅ | `https://maning789link.top/downloads/LaomaAI-1.1.5-setup.exe` | HEAD → 200 / 639,437,816 B |
| 8 | 旧版 1.1.4（升级测试用） | ✅ | `https://maning789link.top/downloads/LaomaAI-1.1.4-setup.exe` | HEAD → 200 / 639,433,570 B |

**下载速度实测**（【已验证】2026-10-23 实测，不是估算）：

| 通道 | 速率 | 639 MB 理论耗时 |
|---|---|---|
| GitHub 直连 | 0.12 MB/s | ≈ 89 分钟 |
| GitHub 走代理 | 2.25 MB/s | ≈ 4.7 分钟 |
| 自建镜像直连 | 0.36 MB/s | ≈ 29 分钟 |

> ⚠️ **不要在没实测的情况下承诺任何速度数字。** 国内用户下载请优先走自建镜像。

### 2.2 仓库内资产

| # | 资产 | 位置 | 状态 |
|---|---|---|---|
| 1 | README（含「我们基于什么」「我们在其上做了什么」两张表） | `README.md`（34,107 B） | ✅ |
| 2 | 许可与归属 | `LICENSE`（AGPL-3.0 全文）/ `NOTICE.txt`（署名 maning636）/ `vendor/VENDOR.md` | ✅ |
| 3 | CI 配置（8 硬门） | `.github/workflows/ci.yml` | ✅ 最新 run 全绿 |
| 4 | Release 流程 | `.github/workflows/release.yml`（329 行） | ⚠️ **tag 触发分支从未实跑验证** |
| 5 | 对外交付口径 | `docs/release-delivery-statement.md` | ✅ 唯一权威 |
| 6 | feature gate 真源表 | `docs/feature-gate-matrix.md` + `.json` | ✅ |
| 7 | 功能盘点与开源边界 | `docs/feature-inventory-and-oss-boundary.md`（73,840 B） | ✅ |
| 8 | 客户端验收清单 | `docs/client-acceptance-checklist.docx`（45,731 B，**41 项 7 组**） | ✅ 已交付，待马哥回传结果 |
| 9 | 待决表（3 张 Word） | `docs/release-finalize-decision-form.docx` 等 | ✅ 已填并执行 |
| 10 | 备份清单生成器 | `scripts/backup/build_backup_manifest.py`（11,875 B） | ✅ 支持 `--verify` 回读重算 |
| 11 | 文档工具链 | `scripts/docs/`（builder + reader + roundtrip test，共 15 个脚本） | ✅ |
| 12 | 实施报告 | `docs/dev-reports/` 43 份 | ⚠️ 40 份停在 10-16 之前 |

### 2.3 运维态（服务器 101.43.65.216）

| # | 项 | 状态 | 位置 |
|---|---|:---:|---|
| 1 | 云端服务 `prism-cloud.service` | ✅ active/running/enabled | `127.0.0.1:8091`（仅 loopback） |
| 2 | 服务器代码副本 | ✅ HEAD=`6af4768`，dirty=0 | `/opt/prism-fusion/app/` |
| 3 | 裸仓库（部署源） | ✅ | `/opt/prism-fusion/repo.git` |
| 4 | Python 虚拟环境 | ✅ | `/opt/prism-fusion/venv/` |
| 5 | 官网 nginx 站点 | ✅ | `/etc/nginx/conf.d/fde.conf` → `root /var/www/fde` |
| 6 | 下载镜像 nginx 段 | ✅ | `location ^~ /downloads/ → alias /var/www/prism-downloads/`；`location = /downloads/latest.yml` 为 no-cache |
| 7 | 官网首页 | ✅ 33,477 B | `/var/www/fde/index.html`（旧版备份 `index.html.bak.20261023_132000`） |
| 8 | 安装包镜像 | ✅ 1.1.4 + 1.1.5 三件套并存 | `/var/www/prism-downloads/` |
| 9 | MariaDB / Redis | ✅ running | 3306 / 6379（**同机其它业务共用，不要动**） |
| 10 | 同机其它服务 | ⚠️ **不要干扰** | `payskill.service`（8090）、`fde-api.service`（8787） |

> **服务器只有 3.6 GB 内存、19 GB 可用磁盘**（【已验证】2026-10-24 实测）。`prism-cloud.service` 已设 `MemoryMax=800M` / `CPUQuota=150%`。

### 2.4 备份（`D:\Prism-Fusion-Backup`）

| # | 内容 | 大小 | 说明 |
|---|---|---|---|
| 1 | 1.1.5 三件套 | 639,437,816 / 650,420 / 347 B | 与 GitHub Release 逐字节一致 |
| 2 | `Prism-Fusion-source.zip` | 46,032,423 B | **= `git archive f36c620`**（与已发布二进制严格对应的源码，1423 条目） |
| 3 | `MANIFEST.txt` | 5,654 B | 14 条目，含 SHA-256 与说明；`--verify` 通过 14 / 不符 0 |
| 4 | `PROJECT_DEVELOPMENT_HISTORY.md` | 159,559 B | ⚠️ **未补 round18 章节** |
| 5 | `_superseded_round18/` | — | 1.1.4 三件套 + 旧源码包 + 旧 MANIFEST + 切 GitHub Release 前的旧官网 |

---

## 3 项目全过程（2026-10-13 → 10-24）

> 全部依据 `git log` 实测重构。提交数按日统计，合计 **114 个提交**（10-13 至 10-23）。

### 阶段 A · 底座与商业化骨架（10-13 ~ 10-16，37 commits）

| 日 | 做了什么 | 关键提交 |
|---|---|---|
| 10-13 | 品牌 `PRISM_` → `LAOMA_`；**C 类云端** `cloud_service`（auth/billing/llm_proxy/payment）；**C 类客户端**（双通道 cloud_gateway + prompt 分层 + key 剥离 + 前端登录/license UI + Electron safeStorage）；pyarmor 加固试点 | `09ff37d` `4866d9b` `3aeae1b` `be839a7` |
| 10-14 | 支付遗留补齐（退款端点 + 日终对账 + 订单超时关闭）；客户端网关统一；CI 接入 cloud_service 测试（conftest 适配层 + 硬门 job）；LLM 代理流式端点 | `ef383ee` `c3a2c7a` `6a44015` |
| 10-16 | CORS 中间件 + `.env.example`(37 项) + 云端启动器；vitest 基建；订阅态/离线态 tier 分层回归；**微信支付 APIv3 真实对接**；**支付宝 OpenAPI 真实对接**；Celery 无害探针 + 启动残余 **4.86s → 2.77s**；部署产物（nginx 片段 / systemd unit / 幂等部署脚本）；前端 tsc 存量错误归零；E2E 不再污染 C 盘 | `87d3110` `16b4cee` `c198b04` `c2dac24` `4c1c981` |

### 阶段 B · 五模块复刻与开源准备（10-18 ~ 10-20，5 commits）

| 日 | 做了什么 | 关键提交 |
|---|---|---|
| 10-18 | health-check fast 端点（**18 ms**，跳过 DB/AI/preflight）；MariaDB 自动备份脚本（轮转 7 天，密码不落盘）；新增前端 ESLint 全量 lint job | `766ac92` `6f51b3c` `369c2bd` |
| 10-19 | **5 模块复刻 + Open Core + 健壮性修复 + Community 打包**（本项目 43 份 dev-reports 的主要来源）：M1 AI 生图 / M2 智能体风格训练 / M3 积分账本 / M4 场景向导 / M5 图片编辑器 | `ac8978e` |
| 10-20 | GitHub 开源准备 + M4 骨架填充 + DOM 测试 + NSIS 打包修复 + 文档总览 | `2328999` |

### 阶段 C · 产品化收尾 + SaaS 化 + 开源边界落地（10-21 ~ 10-22，42 commits）

| 日 | 做了什么 | 关键提交 |
|---|---|---|
| 10-21 | `.gitattributes` 锁定换行符；redis 约束对齐 `<5`；Electron 开发模式 userData 改相对项目根推导；**`backup_mariadb.sh` 修三处缺陷（该脚本从未成功执行过）**；端到端链路审计；**打通 10 条断链**（审核队列 + SSE 流式代理 + 侧边栏全量化）；路由 0 孤儿；功能清单与开源边界待勾选文档；许可口径统一 AGPL-3.0 | `da9b123` `8ccf090` `0d5075f` `3415123` `226dbf3` `7287d03` |
| 10-22 | README 拆出「我们基于什么」「我们在其上做了什么」两张表；**统一产物总线**（生图→上传→渲染→审核→发布 串成一条流水线）；开源边界拍板写回 + feature gate 矩阵；**B2 云端 prompt 正文移出开源树**（公开仓留 stub，Pro 打包注入）；**P0 修 feature_gate 漏 import select（付费 Pro 用户被静默降级）**；**B1 注册码模块**（Ed25519 签发端 + 客户端离线校验 + 双轨判定）；**D4 只读守卫**（从「有机制」变「真拦截」）；B1 前端入口；版本 bump 1.1.1；清 U+FFFD 乱码；**砍掉线上支付，改注册码 + 人工充值**；个人微信码替换占位图；1.1.2；**1.1.3 固化官方云端地址**（修 1.1.2 安装包内置 localhost） | `7dd9237` `6879212` `2aba479` `719c27c` `7983f64` `60ea8e9` `a605e39` |

### 阶段 D · 合并单一客户端 → 1.1.5 → 开源发布 → 收尾（10-23，30 commits）

**D1 · 打包形态收口（00:24 – 02:28）**

| 提交 | 内容 |
|---|---|
| `94c66a9` | Pro 版 extraResources 过滤掉 `.env` + 两个打包脚本加构建期守卫 |
| `889b3ec` | **彻底删除平台支付**（支付宝/微信支付），商业闭环收敛为个人微信 + 注册码 |
| `d264d4f` | 客户端分级改读**本地交集**，补 plan 派生 + 12 项 flag |
| `e6c1925` | **合并为单一客户端** + 修 `latest.yml` 名字对不上（根因修复）→ **v1.1.4** |
| `2f59d05` | `build-package.bat` 改纯 ASCII + 出客户端发布形态待决表 |

**D2 · 1.1.5 产出与验收（02:39 – 03:53）**

| 提交 | 内容 |
|---|---|
| `1507211` | PROJECT_OVERVIEW 刷到 v1.1.4 |
| **`f36c620`** | **修 1.1.5 客户端三处真缺陷**（云端地址读取 / 数据目录劫持 / 联系页露变量名）→ **产出 1.1.5 安装包的提交** |
| `85e9694` | 修出货面双重编码乱码与源文件 BOM |
| `66ba5a5` | 出客户端人肉验收清单（33 项可勾选 Word 表） |

**D3 · 开源发布与 CI 全绿（13:03 – 15:37）**

| 提交 | 内容 |
|---|---|
| `c160bf1` | 开源仓库指向 `maning636/laoma-ai-workbench` |
| `538159c` | Release 已存在时跳过重打包（防覆盖已发布资产） |
| `adec916` | release 构建注入云端地址 + **仓库归属切到 maning636** |
| `ab48194` | 修后端 ruff 8 条 F821 真 NameError |
| `d27c980` | ESLint 全量检查清零（**121 → 0**） |
| `1f90fba` | **CI Node 20→22** + cloud_service 补 cryptography/redis/uvicorn |
| `11cc1f7` | 补 cryptography 依赖声明 + **新增依赖声明闸门（双向自测）** |
| `0df4683` | 修后端 pytest 陈旧断言/陈旧接口，**软门转硬门** |
| `d1fee57` | 修 cloud_service 注册码篡改用例随机失败（**1/16 概率炸**） |
| `206a202` | **把 license 护栏测试纳入 CI 硬门** + 修一条早就失效的路由枚举用例 |

**D4 · 待决表落地与收尾（15:53 – 19:20）**

| 提交 | 内容 |
|---|---|
| `e9d76ab` | 新增《开源发布收尾 · 待决表》+ 回读脚本 + 往返测试 |
| `17c75e3` | 待决表 P5 事实修正（官网已有个人微信二维码，缺的是微信号文字） |
| `45e71e4` | **P7：平台密钥未配置时关掉云端 AI / TikHub 入口并给出明确中文提示** |
| `312e4ba` | NOTICE 署名改 maning636 + 发布口径文档 + D1–D5 追认确认表 |
| `b155cd2` `731dea2` | 备份 round18 工具链 + MANIFEST 表头消歧 |
| `6af4768` | 验收清单补「组 7 · 从 1.1.4 升级」→ **41 项** |

### 3.1 版本迭代轨迹（一条线看全）

| 版本 | 产出提交 | 解决了什么 |
|---|---|---|
| 1.1.1 | `24bbbdd` | 开源边界落地后第一个正式版本号 |
| 1.1.2 | `512236c` | 个人微信码替换占位图 |
| 1.1.3 | `a605e39` | **固化官方云端地址**（修 1.1.2 安装包内置 localhost 的事故） |
| 1.1.4 | `e6c1925` | **合并为单一客户端** + latest.yml 根因修复 |
| **1.1.5** | **`f36c620`** | **修三处客户端真缺陷**（当前对外发布版本） |
| 1.1.6 | *未做* | 计划补：安装器署名切 maning636 + P7 未配置提示进包 |

---

## 4 关键技术决策台账

> 这一节回答「为什么是这样」。接手后要改架构前，先看这里。

| 编号 | 决策 | 为什么 | 否掉了什么 |
|---|---|---|---|
| **P1=A** | 官网保留 GitHub + 自建镜像**双通道** | 0 成本；等真有用户反馈再调优 | JS 智能分流、升带宽、上 COS |
| **P2=A** | `NOTICE.txt` 第 3 行版权署名 `maning636` | 归属一次性切干净 | 保留原作者署名 |
| **P3=A** | `build.publish` 暂留 **generic 自建通道**，自动更新不切 GitHub provider | GitHub 直连 0.12 MB/s → 639 MB 约 89 分钟，对国内用户是**净退化** | 切 GitHub provider |
| **P4=A** | D1–D5 按实际落地追认（D1=A D2=A D3=B D4=A D5=A） | 公开仓能 clone/看历史/提 issue，比静态 zip 更彻底，AGPL「提供对应源码」义务直接履行 | D3=A（官网放源码 zip） |
| **P5=B** | 官网只留二维码，**不公开微信号文字** | 防爬号批量加好友 / 发广告 | 公开号码 |
| **P6=C** | 先做备份 round18，升级安装验收暂缓 | 备份是 AGPL 义务的兜底，成本低；升级验收需干净机 | 直接做升级验收 |
| **P7=B** | 不给密钥 → 显式关掉依赖平台密钥的能力 | 商业上不让出订阅体系 | 「功能全关」（会砍掉判档模型另一半） |
| **B2** | 云端 prompt 正文移出开源树（留 stub，Pro 打包注入） | prompt 正文是核心资产 | 把 prompt 正文公开 |
| **D4** | 注册码只读守卫「从有机制变成真拦截」 | 有机制不等于有效，护栏必须真拦 | 只写文档不做拦截 |
| **单一客户端** | 删掉独立 Community 安装包 | 官网只挂一个入口，客户端内分档 | 两套安装包并行 |
| **支付删除** | 支付宝/微信支付代码彻底删除 | 个人收款 + 人工发码，零支付通道成本 | 保留在线支付代码 |

### 4.1 P7 的关键设计（最容易做错的一处）

> **P7=B 的边界说明：为什么不是「把功能全关掉」**

云端订阅除 LLM 额度外，还决定 `max_accounts` / `max_platforms` / `agent_quota` / `persona` / `proxy_management` / `stream_chat` / `cloud_prompt` / `campaign_orchestration` 等 flag —— **关掉账号体系等于把「注册码 ∩ 云端订阅 = Pro 判定」的另一半砍掉**。
所以：**订阅与账号保留**，只关掉依赖平台密钥的部分（云端 AI 对话入口、TikHub 采集入口）。
TikHub key 是**用户自己在设置页填**的（存 `ai_model_configs`），不是平台统一发的 → 配置卡保留，只隐藏账号页「点了必然失败」的「补全」按钮。

**三态判定规则（务必背下来）**：

| 服务端返回 | 前端判定 | 行为 |
|---|---|---|
| `api_key_configured === false` / `tikhub_enabled === false` | `unavailable` | **隐藏入口** |
| 网络抖动 / 超时 / 5xx / 字段不认识 | `unknown` | **保持现状**（不隐藏） |
| 明确配置好了 | `available` | 正常显示 |

> **`unknown ≠ unavailable` 是「自动隐藏入口」类改动的头号线上事故来源。** 接手方若要扩展这套逻辑，务必保留这条语义。

---

## 5 现状快照

> 接手时的真实状态，全部【已验证】2026-10-23/24 实测。

### 5.1 代码与 CI

| 项 | 值 |
|---|---|
| 本地 HEAD | `c24a11d`（`main`，工作区干净，**[待推送]** 三处同步以 CI run 为准） |
| `origin/main` | `c24a11d` **[待推送]** 三处同步以 CI run 为准 |
| `prism-server/main` | `c24a11d` **[待推送]** 三处同步以 CI run 为准 |
| 服务器 `/opt/prism-fusion/app/` | HEAD=`c24a11d` **[待推送]**，dirty 计数 = 0，三处同步以 CI run 为准 |
| CI 最新 run | success，**8 硬门全绿**（E2E packaged 按预期 skipped） |
| `upstream` remote | `Laihiujin/Prism`（只读参考，不合并、不 force-push） |

### 5.2 技术栈（【已验证】读 `package.json` / `requirements.txt`）

| 层 | 选型 |
|---|---|
| 前端 | Next.js `^16.0.10`（App Router）+ React `19.2.0` + TypeScript `5.9.3` + Tailwind `^3.4.1` + shadcn/ui + vitest `^3.2.7` |
| 桌面 | Electron `^39.2.7`（**实际安装 39.2.7**）+ electron-builder `^24.9.1` + Inno Setup |
| 后端 | FastAPI `0.133.1` + uvicorn `0.41.0` + SQLAlchemy async + Celery + patchright；Python `>=3.11` |
| 云端 | FastAPI + SQLAlchemy + Redis + Pydantic |
| 依赖 | 根 `requirements.txt` 42 行；`prism_backend/requirements.txt` 是 `-r ../requirements.txt` 的引用行 |

> ⚠️ **文档漂移提示**：`docs/PROJECT_OVERVIEW.md` §3 技术栈表里写的是「Electron 28.0.0 + electron-builder 24.13.3」，与 `package.json` 和实际安装版本（39.2.7 / 24.9.1）**不一致**。以 `package.json` 为准。接手方若改这行，请一并核对 `node_modules/electron/package.json` 的 `version`。

### 5.3 目录地图（只列需要接手的）

| 路径 | 规模 | 职责 |
|---|---|---|
| `prism_frontend/` | ts/tsx 302 | 前端。`src/app/` 页面，`src/components/<域>/` 组件，`src/lib/` 纯函数层 |
| `prism_backend/` | py 562 | 本地后端。`fastapi_app/`（FastAPI 应用）、`app_new/platforms/`（平台适配器）、`uploader/`、`fusion_ai/` |
| `cloud_service/` | py 38 | 云端服务。`billing/feature_gate.py` 是 flag 真源；`llm_proxy/`；`_pro_assets/`（**gitignored**） |
| `desktop-electron/` | py 1958 | Electron 壳。`src/main/index.js` 主进程；`installer.iss`；`dist-out/v*` 打包产物 |
| `scripts/` | py 99 | 工具链。`packaging/` `deploy/` `ops/` `license/` `docs/` `backup/` `tests/` `maintenance/` |
| `docs/` | md 70 | `dev-reports/` 43 份 + 口径文档 + 待决表 |
| `tools/` | py 97 | Hermes 技能与工具 |
| `vendor/` | — | 第三方归属（VENDOR.md） |
| `_caches/` `tmp/` `_deploy_inputs/` `_appdata_electron/` | — | **本地运行时/缓存，全部 gitignored** |

### 5.4 凭据位置（**只列路径，不含任何密钥值**）

| 用途 | 位置 |
|---|---|
| 注册码签发私钥 | `D:\Prism-Fusion-Backup\license-keys\prism_license_ed25519.pem` |
| 云端测试账号 | `D:\Prism-Fusion-Backup\_acceptance\cloud_test_account.txt` |
| 测试注册码原文 | `D:\dim开发\Prism-Fusion\tmp\_test_license.txt` |
| 服务器云端 env | `/opt/prism-fusion/.env.cloud`（mode 600） |
| 服务器 DB 凭据 | `/opt/prism-fusion/.db_credentials/`（mode 700） |

> **凭据一律不进仓库、不进文档、不进 git commit message、也不进 issue/PR 描述。**

---

## 6 未来计划

### 6.1 已排期但等马哥放行（1 条）

| # | 任务 | 内容 | 成本 | 阻塞 |
|---|---|---|---|---|
| 1 | **1.1.6 重打包** | ① 安装器发布者 `Laihiujin` → `maning636`（对应 `adec916`）② P7 的中文「未配置」提示进包（对应 `45e71e4`）③ 顺带发新 Release → 官网换版 → 备份 round19 | 打包约 1 h + 发布链路 | **需 ≥4–5 GB 空闲内存**（本机总 15.25 GB，当时空闲仅 0.99 GB）+ 马哥拍板 |

> 2026-10-23 夜马哥明确拍板「**暂缓，等一会儿，电脑要有其他用途**」。**未获放行前不要擅自启动打包。**

### 6.2 等待期可做（不占内存峰值、不需外部输入）

| # | 任务 | 说明 | 预估 |
|---|---|---|---|
| 2 | **前端向导平台列表对齐后端** | 知乎/头条/西瓜后端无发布通道 → 要么补后端、要么前端标注「暂不支持」；同时把后端有而前端没列的 baijiahao/tiktok/youtube 补上 | 2 h |
| 3 | **`release.yml` tag 触发流程首次实跑验证** | 该分支从未在 GitHub 上跑过。⚠️ **严禁手动 dispatch**（会覆盖已验收的 1.1.5 资产或产出非预期 v1.1.6）→ 用一个测试 tag 验 | 30 min + 出包内存 |
| 4 | 补仓库社区文件 | 缺 `CODE_OF_CONDUCT.md` / `SECURITY.md` / `CHANGELOG.md` / `.github/ISSUE_TEMPLATE/` 两个模板 | 1 h |
| 5 | 备份收尾 | `PROJECT_DEVELOPMENT_HISTORY.md` 补 round18 章节；写 `_verify/` 的 round18 最终核实脚本（round17 有 `final_verify_round17.py` 可参照） | 1 h |
| 6 | 补 dev-reports 收官报告 | 把 10-17~10-24 这段写成正式 dev-report，闭合 §0.1 指出的文档缺口（本文档可作初稿） | 1 h |

### 6.3 需要马哥提供输入（2 条）

| # | 任务 | 需要什么 | 不给的默认行为 |
|---|---|---|---|
| 7 | **41 项验收结果处理** | 马哥填好的 `docs/client-acceptance-checklist.docx` 回传 | 组 7 数据保留类问题按最高优先级修 |
| 8 | 开启云端 AI / 数据回收 | `CLOUD_LLM_API_KEY` / `TIKHUB_API_KEY` | 按 P7=B 保持入口隐藏 + 中文「未配置」提示 |

### 6.4 路线图（长期）

| 方向 | 内容 | 依赖 / 预估 |
|---|---|---|
| 平台覆盖 | 补知乎/头条/西瓜的发布通道，或明确只做「内容生成 + 手动发布」 | 每平台约 2–5 人日 |
| 自动更新升级 | 切 GitHub provider | 等国内带宽或镜像条件成熟，否则是净退化 |
| 端到端自动化 | `e2e-packaged` 接入 self-hosted Windows runner（label: `self-hosted, windows, laoma-e2e`），当前**永远 skip** | 需一台常开 Windows 机 |
| 团队协作 | 多用户 + 权限（`team_members` flag 已预留） | 见 `docs/dev-reports/2026-10-16-open-core-strategy.md` |
| 私有化企业版 | Ed25519 + 硬件指纹授权（可插拔引入） | 5–8 人日，见 `authorization-vs-registration.md` |

---

## 7 已知缺口与未完成（诚实清单）

### 7.1 真缺陷（建议优先修）

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 1 | 前端向导多列 3 个后端无发布通道的平台 | `prism_frontend/src/components/wizard/scenarios.tsx:231-240` | 用户选了知乎/头条/西瓜，走到发布会失败。 **已于 2026-10-24 修复**（`f8f54d1`，无通道平台禁用+标注；baijiahao/tiktok/youtube 有工具无登录适配器仍不入向导） |
| 2 | 1.1.5 安装器发布者仍是旧署名 | `desktop-electron/package.json`（`adec916` 之后才改） | 包内元数据与仓库 NOTICE 不一致，1.1.6 才解决 |
| 3 | P7 中文「未配置」提示不在已发布包内 | 已发布前端产物 P7 标记命中 0 次 | 1.1.6 才解决 |
| 4 | `release.yml` tag 触发分支从未实跑 | `.github/workflows/release.yml` | 下次发版是「盲发」 |
| 5 | ~~仓库缺 `CODE_OF_CONDUCT` / `SECURITY` / `CHANGELOG`~~ **已于 2026-10-24 补齐**（本次收尾批），ISSUE_TEMPLATE 三件套经核实早已存在（commit `2328999` 引入），本行原口径过时 | 仓库根 / `.github/` | 开源社区合规缺件 |
| 6 | `prism-cloud.service` 的 `Documentation=` 指向 `docs/deploy-README.md`，但该文件**仓库与服务器都不存在** | `/etc/systemd/system/prism-cloud.service` | 悬空指针，服务运维人员点不到手册。修法：补该文件，或把 `Documentation=` 指向 `docs/dev-reports/2026-10-13-deployment-guide.md`。**仓库文件已于 2026-10-24 修复**（`5bc03d5` + `f0fd95d`，Documentation= 已改指 `docs/dev-reports/2026-10-13-deployment-guide.md`；服务器 unit 同步在收尾批） |

### 7.2 决策「不做」（不是缺陷，别去"修"）

| 不做 | 决策 | 原因 |
|---|---|---|
| 不切 GitHub provider（自动更新） | P3=A | 国内 0.12 MB/s → 89 分钟，是净退化 |
| 不升服务器带宽 / 不上 COS | P1=A | 现状双通道 0 成本 |
| 不公开微信号文字 | P5=B | 防爬号 |
| 不提供云端 LLM / TikHub 密钥 | P7=B | 走「关入口 + 明确提示」兜底 |
| 不做 1.1.4→1.1.5 升级安装验收 | P6=C | 备份已完成；升级验收需干净机 |

### 7.3 等外部输入

| # | 缺口 | 需要什么 |
|---|---|---|
| 1 | 1.1.4 → 1.1.5 升级安装验收（组 7，8 项） | 一台干净 Windows 机 + 马哥操作 |
| 2 | 云端 LLM 对话真实可用 | `CLOUD_LLM_API_KEY` |
| 3 | TikHub 数据采集真实可用 | `TIKHUB_API_KEY` |

### 7.4 文档缺口

| # | 缺口 | 说明 |
|---|---|---|
| 1 | `docs/dev-reports/` 缺 10-17~10-24 收官报告 | 本文档 §3 可作初稿。**已于 2026-10-24 补齐**（`docs/dev-reports/2026-10-24-final-sprint-handover.md`，本文档 §3 压缩改写进 dev-report 体例） |
| 2 | `PROJECT_DEVELOPMENT_HISTORY.md` 缺 round18 章节 | 备份目录内。**已于 2026-10-24 补齐**（HISTORY 第二十六章 + `_verify/final_verify_round18.py` 74/74 PASS） |
| 3 | 备份 `_verify/` 缺 round18 最终核实脚本 | round17 有 `final_verify_round17.py` 可参照。**已于 2026-10-24 补齐**（HISTORY 第二十六章 + `_verify/final_verify_round18.py` 74/74 PASS） |

---

## 8 坑与陷阱（最值钱的一章）

> 这一章每一条都是**本项目实际踩过**的，不是通用鸡汤。**动手前先扫一遍。**

### 8.1 Git 与推送

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| G1 | `git push` 到 github.com 挂死，几百秒零输出 | 本机全局配了 `http.proxy`/`https.proxy` = `http://127.0.0.1:7897`，故障时刻走代理的 TLS 握手失败。**同一天内直连/代理会翻转，且是按 host 分的** | **每次推之前先探两条链路**（`D:\cache\tmp\_probe_links.py`：对 `github.com`/`api.github.com` 分别做直连 TLS + 代理 CONNECT），按结果选 `-c http.proxy=`（直连）或 `-c http.proxy=http://127.0.0.1:7897`（走代理）。**不要硬编码** |
| G2 | `git add -A` 把运行时数据带进仓库 | 仓库有大量本地运行时目录（`_caches/` `tmp/` `_appdata_electron/` `_deploy_inputs/` `data/` `logs/`） | 逐个显式 `git add <path>`。**禁用 `git add -A` / `git add .` / stash / `reset --hard` / `checkout ./` / `clean` / force push / `--no-verify`** |
| G3 | `git ls-tree` 中文路径被八进制转义 → 假报「仅在 zip / 仅在 tree」差异 | Git 的 `core.quotepath` 默认行为 | 加 `-c core.quotepath=false` |
| G4 | `git push` 写 stderr 触发 `NativeCommandError`（即使成功） | PowerShell 把原生命令的 stderr 当错误 | 不用 `$ErrorActionPreference='Stop'` 包原生命令；用 `Select-String -Pattern 'main ->'` 取结果行 |
| G5 | `commit message` 写绝对路径会泄露本机路径 | 签发脚本曾带本机绝对路径 | 提交前扫一遍 diff 里的路径与账号标识（见 `AGENT.md` → Repo Hygiene） |

### 8.2 CI 与测试

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| C1 | 本地 Windows 全绿，CI 红 | **CI 是 Linux** | 本地通过 ≠ CI 通过，**必须看 GitHub run 结果** |
| C2 | 6 个 DOM 测试文件全挂：`Cannot read properties of undefined (reading 'bind')` | jsdom 30.1.3 内嵌 undici 8.12.3，`engines` 要求 node ≥ 22.19.0 | **Node 22 是硬性下限**，不能用 Node 20 |
| C3 | `pytest cloud_service/test_llm.py` → `0 items` exit 5 | 这些是**自运行脚本**（末尾 `if __name__ == "__main__": run()`），不是 pytest 用例 | 传**目录**（`pytest cloud_service`），或直接 `python cloud_service/test_llm.py` 看 `ALL TESTS PASSED` |
| C4 | 依赖声明闸门永远返回 OK | 打包产物里有整份拷贝的第三方包目录，形成本地目录影子 | 闸门必须带 **`--self-test` 反向自测**：逐个删掉候选包的声明，要求它们必须被重新报出来，否则闸门失灵 → job 红 |
| C5 | `app.routes` 看不到 included router | FastAPI 的 include_router 不出现在 `app.routes` | 看 `app.openapi()["paths"]` |
| C6 | 注册码篡改用例偶发失败（1/16 概率炸） | 测试自身缺陷 | 已修于 `d1fee57` |
| C7 | `Select-Object -First` 截管道 → Python 收到 exit 4294967295 | 管道提前关闭 | 脚本输出**重定向到文件**再读，别在管道里截断 |
| C8 | `pytest cloud_service` 单文件没收集到用例 | 同 C3 | 同 C3 |

### 8.3 Windows / PowerShell

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| W1 | `Get-Content` 读 UTF-8 文件中文变乱码 | PowerShell 5.1 **默认按 ANSI 读** | 加 `-Encoding UTF8`，或用 read 工具 |
| W2 | `>` 重定向写出的文件是 UTF-16 | PowerShell 5.1 的 `>` 默认 UTF-16LE | 用 `Out-File -Encoding UTF8`，或读回时 `encoding="utf-16"` |
| W3 | `.ps1` 里中文在别的机器上乱码/报错 | **PowerShell 5.1 按 ANSI 读 `.ps1`** | `.ps1` 必须**纯 ASCII**。中文要用字符码点数组构造（如 `[char[]]` + 十六进制码点序列） |
| W4 | `.bat` 里中文注释行被 cmd 当成命令执行 | cmd 按控制台 ANSI 码页读批处理，文件头的 `chcp 65001` 对后续行**不可靠** | `.bat` 必须**纯 ASCII + CRLF**，注释统一用 `rem`（不是 `::`）。改完自检：非 ASCII 行数 = 0、裸 LF = 0、无 BOM |
| W5 | `$(...)` 在 PowerShell 里被本地求值 | 本地 shell 就展开了 | 远端复杂命令**走上传 .sh 脚本再执行** |
| W6 | ssh 传参会吃掉双引号 | 双层 shell 解析 | 远端命令写成脚本文件传上去执行 |
| W7 | `& ssh` 传参错位 | PowerShell 的参数展开 | **必须用数组**：`& ssh @a` |
| W8 | scp 报路径错 | 目标 host 没写进目标路径参数 | `scp @opts '本地' 'root@host:/tmp/x.sh'` |
| W9 | `python -c "..."` 里放中文 → 语法错 | 命令行编码 | 中文**不要放进 `python -c` 内联命令** → write 工具写文件 + Python 读文件 |
| W10 | Windows 控制台是 GBK | 系统默认代码页 | 脚本里**不要用 ❌/✅ 等非 GBK 字符**；subprocess 读子进程输出要显式 `encoding="utf-8", errors="replace"` |
| W11 | `edit` 工具在 CRLF 文件上多行匹配 NOT FOUND | 行尾不匹配 | 用 **Python 脚本按 CRLF 精确替换**，脚本自适应行尾 |
| W12 | Next.js 生产构建报 `Zone Allocation failed` | **内存不足**（本机总 15.25 GB，空闲 <2 GB 时必现） | 打包前确认空闲 ≥4–5 GB |

### 8.4 打包与发布

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| P1 | electron-builder 挂：`ECONNREFUSED 127.0.0.1:7897` | 本机环境变量有 `HTTP_PROXY`/`HTTPS_PROXY`，代理没开时下载 electron 二进制连不上（**不是代码问题**） | 构建脚本里摘掉代理环境变量；镜像走 npmmirror。查代理来源要查**三处**：环境变量、`npm config get proxy`、`.npmrc`（这次只有环境变量有） |
| P2 | `latest.yml` 的 path 与磁盘文件名对不上 → 自动更新静默失效 | electron-builder 的 `artifactName` 含中文时 `isSafeGithubName` 正则 `/^[0-9A-Za-z._-]+$/` 不通过 | `artifactName` 用**纯 ASCII**（现为 `LaomaAI-${version}-setup.${ext}`），**别指望后处理** |
| P3 | `latest.yml` 里名字对不上（1.1.4 时代的老 bug） | 版本号匹配不精确，旧包残留导致静默发错包 | 打包脚本按版本号精确匹配（已修于 `e4fb655`） |
| P4 | `build-package.bat` 块内 echo 的括号导致 if 块提前闭合 | 批处理语法 | 修于 `3e205f0` |
| P5 | 解 asar 后文件写到了 cwd | `asar extract-file` 的行为 | 必须用 `extract` 到临时目录，**不能用 `extract-file`** |
| P6 | asar 内 package.json 与仓库 `package.json` 比对永远不符 | electron-builder 生成的是**精简版**（389 B vs 7,004 B） | 本就不同，不可直接比。要看 `laomaCloudUrl` 只能读 asar 内那份 |

### 8.5 运维与服务器

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| S1 | nginx 静态文件 **403**（看起来像"文件不存在"） | `alias` 目标落在权限过严的父目录下，worker（`nginx`/`www-data`）穿不过去 → 403 而非 404 | 看**父目录**权限（`stat -c '%A %U:%G %n'`），不是目标文件本身。**首选把可公开文件移出敏感父目录**（本项目：下载目录从 `/opt/prism-fusion/`（700）挪到 `/var/www/prism-downloads/`）；**不要**为了图省事 `chmod o+x /opt/prism-fusion` |
| S2 | nginx 静态文件加 `Accept-Ranges` 出现两个同名头 | nginx 已自带 | **不要**在 location 里再 `add_header Accept-Ranges bytes;` |
| S3 | 部署脚本 `backup_mariadb.sh` 从未成功执行 | 三处缺陷：here-string 只读首行致 `DB_PORT` 为空、凭据未载入、未用 `--defaults-file` | 已修于 `8ccf090` |
| S4 | `redis>=5` 与内置 Redis 5 不兼容（RESP3/HELLO） | 版本冲突 | **必须 `redis<5`**（`031b008` 已对齐 `pyproject.toml` 与 `requirements.txt`） |

### 8.6 代码与验证方法论

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| V1 | 「验证通过」但被测路径其实没生效 | 默认路径与被测路径**共享同一可观察输出** | 验证改写/覆盖的那条路径时，用**只有它能产生的值**（专用变量名、专用 id、专用色值）。断言要能区分「这条路径生效」与「别的路径顺便生效」 |
| V2 | 断言字符串误伤 | 断言写成「正文里不能出现『控制在』」，命中了「标题长度控制在 20 字内」 | 写成上下文敏感形态，如 `/控制在\s*\d{3,}/` |
| V3 | 白名单判断永远不过，整段逻辑静默失效 | `RegExpExecArray`（`RegExp.prototype.exec` 的返回值）**没有 `lastIndex` 属性** —— 那是 `RegExp` 对象自己的 | 用正则实例上的 `placeholder.lastIndex`。`cursor = match.lastIndex` 会得到 `undefined` → `str.slice(undefined)` = `str.slice(0)` 取回整串 |
| V4 | React 受控 input 匹配不到 | 默认 `type=text` 时**不写 attribute** | 用 property 过滤：`input.type === "text"`，别用 `querySelectorAll('input[type=text]')` |
| V5 | 行内代码从中间被截断 | `.gt-code` 是**代码块**样式（`pre-wrap` + `break-all`），被当行内用 | 复用样式类前先确认它的**原始场景**；需要行内版本就**另加修饰类**（`<原类> <原类>--inline`），不要改原类。**断字类 CSS 在行内元素上几乎总是 bug** |
| V6 | 单文件差分网对「模块级 import 的引用方」是结构性盲的 | `from x import y` 在 import 那一刻就绑死，改绑对它无效 → 差分空转假通过 | 交叉差分网：**加载契约之前**把旧版文件装进 `sys.modules`，并把引用方从 `sys.modules` 驱逐让契约重新 import |
| V7 | 差分网「0 差异」其实是假通过 | 原版副本的 `__file__` 指向临时目录 → 相对路径查找必然失败 | 原版副本加载后设 `mod.__file__ = str(REPO / rel)`（`Path(__file__)` 在函数体内求值，导入后再改有效） |
| V8 | `pytest.mark.parametrize` 只覆盖类方法 → 模块级用例两边都抛同错 | 参数没传进去 | parametrize **两种位置都要展开**；且 `--mutate` 模式下**必须报出 ≥1 条差异**，否则这张网是空转的 |

### 8.7 架构与业务逻辑

| # | 现象 | 根因 | 修法 |
|---|---|---|---|
| A1 | 付费 Pro 用户被**静默降级**成限制功能版 | `feature_gate.py` 漏 `import select` | 已修于 `6879212`。**加 flag 时务必查 import** |
| A2 | 客户端内出现 `NEXT_PUBLIC_` 之类的开发者变量名 | 渲染时把内部变量名直接吐给用户 | 1.1.5 已修（`f36c620`），见验收清单 C4 |
| A3 | 安装包把用户数据写到了非预期目录（数据目录劫持） | 打包态 `userData` 推导错 | 1.1.5 已修（`f36c620`），见验收清单 G8 |
| A4 | 云端对话打到了 `localhost` | 安装包内置的云端地址是本地 | 1.1.3 已修（`a605e39`）。**改云端地址必须重新打包验证** |
| A5 | 出货面双重编码乱码 | 源文件 BOM + 编码链路叠加 | 1.1.5 已修（`85e9694`）。**改中文文件后必须扫 U+FFFD 再收工** |
| A6 | 不知道改的是「默认路径」还是「被测路径」 | 默认值与被测值共用变量 | 见 V1。**用专用变量名**（如 `{{custom}}` 而不是 `{{text}}`） |
| A7 | 云端 prompt 正文误入开源仓 | 边界没做 | 已修于 `7dd9237`。**`_pro_assets/` 由 `.gitignore:317` 排除**，OSS 版 `CLOUD_PROMPTS = {}` 为空。⚠️ **别再去"移出 prompts.py"** —— 那是按错误的记忆去改一个已经正确的边界 |
| A8 | 手写 MANIFEST 哈希必然漂移 | 人工誊抄 | 用 `scripts/backup/build_backup_manifest.py` 生成，`--verify` 回读重算比对 |

---

## 9 接手操作手册（可复跑命令）

> **前置约定**：所有 npm/pip/TEMP/PyInstaller/Electron 缓存必须落 D 盘（`_caches/`、`D:\cache\`），**严禁写 C 盘**。

### 9.1 环境

```powershell
# Python（D 盘独立解释器，不污染系统）
& 'D:\dev\python\python.exe' -V

# Node 22（CI 硬性下限）
& 'D:\dev\node\node.exe' -v

# 依赖安装（前端）
cd 'D:\dim开发\Prism-Fusion\prism_frontend'; & 'D:\dev\node\node.exe' '.\node_modules\npm\bin\npm-cli.js' ci
```

### 9.2 本地起服务

```powershell
# 方式 A：一键拉起完整本地栈（推荐）
& 'D:\dim开发\Prism-Fusion\scripts\launchers\start_stack_prismenv.bat'
# 方式 B：Supervisor 模式
& 'D:\dim开发\Prism-Fusion\scripts\launchers\start_supervisor_prismenv.bat'
# 方式 C：手动逐个启动（仅调试）
& 'D:\dim开发\Prism-Fusion\scripts\launchers\start_backend_prismenv.bat'
& 'D:\dim开发\Prism-Fusion\scripts\launchers\start_frontend.bat'
& 'D:\dim开发\Prism-Fusion\scripts\launchers\start_celery_prismenv.bat'
```

详见 `STARTUP.md`（15,644 B）。

### 9.3 打包

```powershell
# 完整打包（PyInstaller 后端 → electron-builder → Inno Setup）
& 'D:\dim开发\Prism-Fusion\scripts\packaging\build-package.bat'
# 产物目录：desktop-electron\dist-out\v<buildNumber>\
```

**版本顶号**：改 `scripts/packaging/build-version.json`（现为 `1.1.5` / `buildNumber: 5`）。`build-package.bat` 的 5 步是：清残留 → 归档 → 版本顶号 → 重写 `latest.yml` → `verify-release-assets` 守卫。

**打包前必查内存**：本机总 15.25 GB，**空闲 <4–5 GB 时 Next.js 生产构建会 `Zone Allocation failed`**。

### 9.4 发版（GitHub）

```powershell
# 1) 探两条链路，按结果选参数（G1）
$env:PYTHONIOENCODING='utf-8'
& 'D:\dev\python\python.exe' 'D:\cache\tmp\_probe_links.py'

# 2) 推 origin（走代理的写法；直连就把 http.proxy= 换成空）
git -C 'D:\dim开发\Prism-Fusion' -c http.proxy=http://127.0.0.1:7897 -c https.proxy=http://127.0.0.1:7897 push origin main

# 3) 推 prism-server（SSH）
$key = 'D:\dim开发\Prism-Fusion\_deploy_inputs\ssh\prism_deploy_ed25519'
$env:GIT_SSH_COMMAND = "ssh -i `"$key`" -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=15"
git -C 'D:\dim开发\Prism-Fusion' push prism-server main
```

**tag 触发发布**：`git tag v1.1.6 && git push origin v1.1.6` → `.github/workflows/release.yml` 自动出包。
⚠️ 该流程**从未实跑验证过**。⚠️ **严禁手动 dispatch** —— `release.yml` 的 `check` job 会「Release 已存在时跳过重打包」（`538159c`），但手动 dispatch 仍可能产出非预期版本。**首次务必用测试 tag 验证。**

### 9.5 部署到服务器

```powershell
$key = 'D:\dim开发\Prism-Fusion\_deploy_inputs\ssh\prism_deploy_ed25519'
$opts = @('-i', $key, '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15')

# 服务器 fast-forward 同步（脚本走 /tmp）
& scp @opts 'D:\cache\tmp\_sync_app.sh' 'root@101.43.65.216:/tmp/_sync_app.sh'
& ssh @opts 'root@101.43.65.216' 'bash /tmp/_sync_app.sh'

# 重启云端服务
& ssh @opts 'root@101.43.65.216' 'systemctl restart prism-cloud && systemctl status prism-cloud --no-pager'
```

### 9.6 备份

```powershell
$env:PYTHONIOENCODING='utf-8'
# 生成 MANIFEST
& 'D:\dev\python\python.exe' 'D:\dim开发\Prism-Fusion\scripts\backup\build_backup_manifest.py' `
  --backup-root 'D:\Prism-Fusion-Backup' --repo 'D:\dim开发\Prism-Fusion' --source-commit f36c620 --round 18

# 回读校验（逐文件重算 SHA-256 与清单比对）
& 'D:\dev\python\python.exe' 'D:\dim开发\Prism-Fusion\scripts\backup\build_backup_manifest.py' `
  --backup-root 'D:\Prism-Fusion-Backup' --verify

# 源码包（必须与已发布二进制对应，不是 HEAD）
git -C 'D:\dim开发\Prism-Fusion' -c core.autocrlf=false -c core.eol=lf archive --format=zip `
  -o 'D:\Prism-Fusion-Backup\Prism-Fusion-source.zip' f36c620
```

### 9.7 验证

```powershell
# CI 状态
& 'D:\dev\python\python.exe' 'D:\cache\tmp\_gh_ci_new.py' 6af4768 2400

# 客户端验收清单重建 + 回读 + 往返测试
& 'D:\dev\python\python.exe' 'D:\dim开发\Prism-Fusion\scripts\docs\build_client_acceptance_checklist.py'
& 'D:\dev\python\python.exe' 'D:\dim开发\Prism-Fusion\scripts\docs\read_client_acceptance_checklist.py'
& 'D:\dev\python\python.exe' 'D:\dim开发\Prism-Fusion\scripts\docs\test_client_acceptance_checklist_roundtrip.py'

# 改中文文件后必须扫乱码
```

---

## 10 验收与交付确认单

> 可勾选的确认单在 **[`docs/handover/DELIVERY-CHECKLIST.md`](./DELIVERY-CHECKLIST.md)**。
> 请工作组逐项核对并回执。

---

## 11 文档索引

### 11.1 接手先读这四份

| 文档 | 一句话 |
|---|---|
| **本文件** | 交棒入口：全过程 + 交付清单 + 计划 + 坑 |
| [`AGENT.md`](../../AGENT.md) | AI Agent 上下文 + Repo Hygiene + Interface Border Rule + **Push Rules** |
| [`HANDOFF.md`](../../HANDOFF.md) | 技术交接：目录结构、全部后端 API 路由、CLI 用法、端口全景、风格约定、接手检查清单 |
| [`docs/PROJECT_OVERVIEW.md`](../PROJECT_OVERVIEW.md) | 项目总览：定位、能力矩阵、技术栈、五大复刻模块、Open Core 分层、部署状态、39 份 dev-reports 索引 |

### 11.2 口径与决策

| 文档 | 一句话 |
|---|---|
| [`docs/release-delivery-statement.md`](../release-delivery-statement.md) | **对外交付口径唯一权威**：下载地址 / 字节数 / SHA-512 / D1–D5 / 商业与解锁口径 / 本版明确不做的事 |
| [`docs/feature-gate-matrix.md`](../feature-gate-matrix.md) | flag 真源表：判档模型与每个 flag 的实际取值 |
| [`docs/feature-inventory-and-oss-boundary.md`](../feature-inventory-and-oss-boundary.md) | 功能盘点与开源边界（含 D1–D10 拍板记录） |
| [`docs/release-finalize-decision-form.docx`](../release-finalize-decision-form.docx) | 开源发布收尾待决表 P1–P7（已填并执行） |
| [`docs/client-release-decision-form.docx`](../client-release-decision-form.docx) | 客户端发布形态待决表 D1–D5（已追认为确认态） |

### 11.3 操作与部署

| 文档 | 一句话 |
|---|---|
| [`STARTUP.md`](../../STARTUP.md) | 本地启动（Windows 三种方式 + macOS PM2） |
| [`PACKAGING.md`](../../PACKAGING.md) | 打包全流程 |
| [`CONTRIBUTING.md`](../../CONTRIBUTING.md) | 贡献指南 |
| [`scripts/README.md`](../../scripts/README.md) · [`scripts/ops/README.md`](../../scripts/ops/README.md) | 脚本索引 / 运维脚本手册 |
| [`docs/dev-reports/2026-10-13-deployment-guide.md`](../dev-reports/2026-10-13-deployment-guide.md) · [`docs/dev-reports/2026-10-16-server-access-and-deploy-prep.md`](../dev-reports/2026-10-16-server-access-and-deploy-prep.md) · [`scripts/deploy/`](../../scripts/deploy/) | 服务器部署准备、访问方式、nginx 与 systemd 片段、幂等部署脚本 |

### 11.4 实施报告

| 文档 | 一句话 |
|---|---|
| [`docs/dev-reports/`](../dev-reports/) | 43 份实施报告。⚠️ 30 份是 `2026-10-16-*`，7 份 `2026-10-13-*`，1 份 `2026-10-14-*`、1 份 `2026-10-15-*`、1 份 `2026-10-21-*`、1 份 `2026-10-22-*`，另 2 份无日期前缀 |
| [`DEVELOPMENT-RECORD.md`](../../DEVELOPMENT-RECORD.md) | 功能详录（47 KB）：14 个新增模块逐一说明、Hermes 集成架构、平台适配器契约、品牌重命名记录、已知问题 |
| [`PLAN_next_steps.md`](../../PLAN_next_steps.md) · [`PLAN_verification_measures.md`](../../PLAN_verification_measures.md) | 下一步计划 / 验证措施 |
| [`docs/hermes-skills/prism-project-layout/SKILL.md`](../hermes-skills/prism-project-layout/SKILL.md) | **AI Agent 唯一上下文源文件**（目录结构、API 路由、CLI、Hermes MCP 工具清单、服务端口） |

---

## 12 一句话给工作组

> 项目本体已开源并对外发布（`maning636/laoma-ai-workbench`，Release `v1.1.5`，官网下载已通）；**8 天的收官过程没有留下连续文档，这就是本文件要补的**。
> 接手第一步请读 §0（阅读路线）、§4（决策台账，别推翻已拍板的事）、§8（坑，这一章最省时间）。
> 当前唯一在等的外部输入是**马哥的 41 项客户端验收结果**；唯一待放行的是 **1.1.6 重打包**（需 ≥4–5 GB 空闲内存）。
> 任何改动请遵守 `AGENT.md` 的 Push Rules，改中文文件后扫 U+FFFD，提交前 `git status --short`。
