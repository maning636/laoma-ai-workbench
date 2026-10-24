# 老马AI工作台 · 开源发布交付口径

> **版本** v1.1.6　|　**日期** 2026-10-24　|　**对应交付** v1.1.6（Release tag `v1.1.6`）
> **依据** 马哥 2026-10-23 在《开源发布收尾 · 待决表》P1–P7 的 7 项决策；
> 以及客户端发布形态表 D1–D5 的追认（该表 P4=A：「全部按实际落地确认」）。
> **性质** 这是**对外口径**的唯一权威出处 —— 官网文案、README 首屏、客服话术、
> Release 说明一律以本文件为准；本文件与实际不符时以实际为准并改本文件。

---

## 1 一句话

老马AI工作台（Prism-Fusion）以 **AGPL-3.0** 开源，Windows 端交付**单一安装包**
`LaomaAI-1.1.6-setup.exe`（424,671,438 B），**源码走公开 GitHub 仓库**，
**完整版由本地注册码解锁**。

---

## 2 对外下载口径

| 项 | 值 |
|---|---|
| 公开仓库 | https://github.com/maning636/laoma-ai-workbench |
| Release（v1.1.6） | https://github.com/maning636/laoma-ai-workbench/releases/tag/v1.1.6 |
| 安装包 · GitHub 主通道 | https://github.com/maning636/laoma-ai-workbench/releases/download/v1.1.6/LaomaAI-1.1.6-setup.exe |
| 安装包 · 国内镜像兜底 | https://maning789link.top/downloads/LaomaAI-1.1.6-setup.exe |
| 官网 | https://maning789link.top |
| 安装包字节数 | 424,671,438 B（约 405 MiB；官网文案写「约 405 MB」） |
| SHA-512（base64） | `QMtUXm5wYieYoO1TGruttifTZLQ2F2qwz5o4ZkpsNaxwl9Mw8gD6IFdN9e534i3WnxMVfizGXIIyfKbKiNWvYg==` |
| 校验命令 | `Get-FileHash .\LaomaAI-1.1.6-setup.exe -Algorithm SHA512` |

Release 三件套（Windows 资产，GitHub 主通道 / 官网链接 / 磁盘文件同名同大小）：

| 文件 | 字节数 | SHA-256 |
|---|---|---|
| `LaomaAI-1.1.6-setup.exe` | 424,671,438 | `798c468d908eda2020a39a68598fcdc42a83fc6a5c981ce2edfbf88538cae68d` |
| `LaomaAI-1.1.6-setup.exe.blockmap` | 420,890 | `bc6a0df4234bb762b2ca217c57df2a6f6990417e3e6afbae94418b115145d8a1` |
| `latest.yml` | 347 | `9dc32e3259b00de952f018682ec1eb1fd79d7045fb0224934a9b57f9f693224e` |

Release 另含 macOS x64 / arm64 的 `.dmg`、`.zip` 与两个 `.blockmap`、以及 `latest-mac.yml`，共 12 项资产；本口径只覆盖 Windows 主通道，macOS 资产的校验以 Release 页为准。

`latest.yml` 内记录的 `size: 424671438` 与 `sha512` 与磁盘、官网展示值三方一致。

**下载速度实测**（2026-10-23 实测，非估算）：

| 通道 | 实测速率 | 425 MB 理论耗时 |
|---|---|---|
| GitHub 直连 | 0.12 MB/s | ≈ 59 分钟 |
| GitHub 走代理 | 2.25 MB/s | ≈ 3.1 分钟 |
| 自建镜像直连 | 0.36 MB/s | ≈ 20 分钟 |

> 官网主按钮指 GitHub Release，旁边挂自建镜像兜底（P1=A 保留现状双通道）。
> **不要在没实测的情况下承诺任何速度数字。**

---

## 3 本版说明（v1.1.6）

**产出方式**：本版由 CI 全链路产出（`release.yml`：三服务 PyInstaller 构建 + 400 MiB 体积守卫），不再走本地手动构建。

**体积变化**：单包 610 → **405 MiB**（-34%）；官网文案同步为「约 405 MB」。

**与 1.1.5 的差异**：

- **未含 pyarmor 混淆** —— CI 无授权（`SKIP_OBFUSCATE=1`），功能无差；混淆本就形同虚设（源码走公开仓），保留混淆只增加包体与运行开销。
- **体积 -34%**（610 → 405 MiB）。
- **未删 1.1.5**：镜像 `maning789link.top/downloads/` 内 1.1.5 三件套仍在（历史下载不断链），`latest.yml` 已换版指 1.1.6。
- **元数据修正**：先前 1.1.5 安装包内嵌 `package.json` 仍为旧署名 `Laihiujin`（见 §4 说明）；本版重打包后安装包内元数据与仓库一致（`author` / `publisherName` / `repository` 均为 `maning636`）。

**对应源码提交**：`b98c95d`（Release tag `v1.1.6` 指向）；源码包 `D:\Prism-Fusion-Backup\Prism-Fusion-source.zip` 已按该提交重出。

**备份**：round19 已完成（MANIFEST 14/14 verify 通过）。

**本版主要内容**：

- 向导平台对齐（知乎 / 头条 / 西瓜禁用标注）；
- 模型供应商注册表与 OpenRouter 风格管理页；
- toast 去重限流；
- 请求 30s 超时 + 骨架屏 + 懒加载（应用感批）；
- 模块联通 L1–L3（37 表 bootstrap / 归因列 / 审核回写 / 数据归因 / 选题建议 / campaigns 接向导 / 供应商导入通道）；
- 包体瘦身 610 → 405 MiB；
- CI 发版链补全。

---

## 4 客户端发布形态 D1–D5（2026-10-23 追认确认）

追认表：`docs/client-release-decision-form.docx`（v1.1 已确认态）。

| 项 | 确认 | 实际落地 | 证据 |
|---|---|---|---|
| **D1** 安装包命名 | **A** | `build.artifactName = LaomaAI-${version}-setup.${ext}`（纯 ASCII） | 1.1.5 产物名 `LaomaAI-1.1.5-setup.exe`；`latest.yml` 的 `url` / `path` 与磁盘同名，`size` 一致 |
| **D2** 客户端 license 口径 | **A** | 客户端整体标 AGPL-3.0，`LICENSE.txt` 为 AGPL 全文，`NOTICE.txt` 版权署名 `maning636`；Hermes（Nous Research，MIT）随包分发并在 NOTICE.txt 归属 | `desktop-electron/package.json`、`NOTICE.txt`、`vendor/VENDOR.md` |
| **D3** 开源交付形态 | **B** | 源码走**公开 GitHub 仓库**，官网下载区已有源码与 Releases 入口 | 官网「客户端下载」区 `dl-note`；`README.md` 首屏安装包入口 |
| **D4** 完整版解锁方式 | **A** | **本地注册码（Ed25519 验签）决定功能档位**，云端订阅只给额度（账号数 / 平台数 / Agent 配额）；两者取交集派生「完整版 / 限制功能版」 | `docs/feature-gate-matrix.md` §0 判定模型 |
| **D5** 安装包体积 | **A** | 单包 639,437,816 B；官网按 640 MB 量级提示并给 SHA-512 校验 | 1.1.5 产物 + 官网 `dl-size` / `dl-meta` |

> D3 与当初给马哥的建议不同：当初建议 A（官网下载区放源码包），实际落地选了 B（公开 GitHub 仓）。
> 按**实际落地**追认 —— 公开仓能 clone、能看历史、能提 issue，比一个静态 zip 更彻底，
> 且 AGPL「提供对应源码」的义务由公开仓直接履行。

> **已发布 1.1.5 安装包内的元数据仍是旧署名**：`desktop-electron/package.json` 的
> `author` / `publisherName` / `repository` 是在发布**之后**才切到 maning636 的
> （提交 `adec916`，2026-10-23 13:23），所以 1.1.5 安装包内嵌的那份 package.json
> 仍写着 `Laihiujin`。仓库内的 `NOTICE.txt` 已是 `maning636`（P2=A，提交 `312e4ba`）；
> **1.1.6 重打包后**，安装包内元数据才会与仓库一致。

### 已发布二进制 ↔ 源码的对应关系

AGPL 的义务是提供**所分发二进制对应的源码**，不是「仓库最新状态」。本项目的实际情况：

| 事实 | 值 |
|---|---|
| 产出 1.1.5 安装包的提交 | `f36c620`（2026-10-23 03:52:51 提交；构建发生于该提交工作树的 03:31–03:38） |
| 与二进制严格对应的源码包 | 备份目录 `Prism-Fusion-source.zip` = `git archive f36c620`（1423 个文件；1350 个与 git tree 逐字节一致，其余 73 个仅行尾差异，详见备份 `MANIFEST.txt`） |
| 公开仓 main | `ffafd6a` —— **比已发布二进制新**，含发布之后才有的改动 |
| 发布后但不在二进制内的改动 | `adec916` 归属切 maning636、`45e71e4` P7 关闭未配置入口、`312e4ba` NOTICE 署名、`ffafd6a` release.yml 注释 |

> 核验方式：解包 `app.asar` 与 `git show f36c620:<path>` 逐行比对 ——
> `src/main/index.js` 仅差 37 行（33 行是打包时尚未清理的中文注释乱码，2 行是 BOM 加固调用点），
> `src/main/version-catalog.js` 与该提交完全一致；因 asar 内 package.json 实测**无 BOM**
> （首字节即 `{`），那 2 行差异运行时无功能影响 —— 三处客户端真缺陷的修复本身**确已在包内**。
> 反向可证：已发布前端产物里 P7 标记命中 **0 次**，即 P7 不在 1.1.5 包内。

---

## 5 商业与解锁口径

| 项 | 口径 |
|---|---|
| 支付 | 平台支付**已彻底删除**；收款走个人微信 → 人工发注册码 |
| 判档 | 本地注册码 **∩** 云端订阅 → 派生「完整版 / 部分开通 / 限制功能版」 |
| 客户端内切换 | 两个版本在**同一份安装包**内，激活后功能就地打开，不需重装 |
| 自动更新通道 | **generic provider** → `https://maning789link.top/downloads`，客户端自动更新查自建通道的 `latest.yml`，**不查 GitHub**（P3=A 暂留本版不动） |
| 联系方式 | 官网**只放个人微信二维码**，**不公开微信号文字**（P5=B：防止号码被爬去批量加好友 / 发广告） |
| 云端 AI / TikHub | 未配置平台密钥时，客户端**隐藏相关入口**、后端返回明确的中文「未配置」提示（P7=B）；**订阅与账号体系保留**（云端订阅还决定账号数 / 平台数 / Agent 配额） |

### P7=B 的边界说明（为什么不是「把功能全关掉」）

- 云端订阅除 LLM 额度外，还决定 `max_accounts` / `max_platforms` / `agent_quota` /
  `persona` / `proxy_management` / `stream_chat` / `cloud_prompt` / `campaign_orchestration`
  等 flag —— 关掉账号体系等于把「注册码 ∩ 云端订阅 = Pro 判定」的另一半砍掉。
  因此：**订阅与账号保留**，只关掉依赖平台密钥的部分（云端 AI 对话入口、TikHub 采集入口）。
- TikHub key 是**用户自己在设置页填**的（存 `ai_model_configs`），不是平台统一发的 →
  配置卡保留（配好后功能自动可用），只隐藏「点了必然失败」的账号页「补全」按钮。
- 前端三态判定 `available` / `unavailable` / `unknown`：
  **只有服务端明确回 `api_key_configured === false` / `tikhub_enabled === false` 才隐藏入口**；
  网络抖动 / 超时 / 5xx / 字段不认识一律判 `unknown`，保持现状行为。
  （`unknown ≠ unavailable` 是「自动隐藏入口」类改动的头号线上事故来源。）

---

## 6 本版明确不做的事

| 不做 | 决策 | 原因 |
|---|---|---|
| 不切 GitHub provider（自动更新） | P3=A | 自动更新走 GitHub 直连 0.12 MB/s → 639 MB 约 89 分钟，对国内用户是净退化 |
| 不升服务器带宽、不上腾讯云 COS | P1=A | 现状双通道保留，0 成本；等真有用户反馈再动 |
| 不在官网公开微信号文字 | P5=B | 防爬号批量加好友 |
| 不做 1.1.4 → 1.1.5 升级安装验收 | P6=C | 备份 round18 已完成（1.1.5 三件套 + 对齐源码包 + MANIFEST 已刷进 `D:\Prism-Fusion-Backup`）；升级安装验收暂缓（需一台干净机） |
| 不提供 `CLOUD_LLM_API_KEY` / `TIKHUB_API_KEY` | P7=B | 走「功能关掉 + 明确提示」兜底 |

---

## 7 事实来源与复核方式

本文件里的每个数字都有出处，改动前请现查现验：

| 事实 | 怎么复核 |
|---|---|
| 安装包字节数 / SHA-256 | `desktop-electron\dist-out\v5\` 下三件套的磁盘文件 |
| `latest.yml` 内的 size / sha512 | 同上，与磁盘、与官网展示值三方对账 |
| 官网展示的 SHA-512 | 公网首页 HTML 的 `dlSha` |
| 公开仓 / Release 地址 | `maning636/laoma-ai-workbench` 的 Release 页 |
| license / 署名 / publish provider | `desktop-electron/package.json`、`NOTICE.txt` |
| 判档与 flag | `docs/feature-gate-matrix.md` |
| D1–D5 确认结果 | `docs/client-release-decision-form.docx`（回读脚本 `scripts/docs/read_client_release_decision_form.py`） |
| P1–P7 决策原文 | `docs/release-finalize-decision-form.docx`（回读脚本 `scripts/docs/read_release_finalize_decision_form.py`） |
| 源码包 ↔ 二进制对应关系 | 备份 `MANIFEST.txt` 说明第 5–7 条；`scripts/backup/build_backup_manifest.py --verify` 可随时复校 |
| 备份清单完整性 | `python scripts/backup/build_backup_manifest.py --backup-root <备份目录> --verify`（逐文件重算 SHA-256 与清单比对） |

> 凭据（注册码私钥、云端账号密码）**一律不写进本文件、不写进仓库、不进 git**。
