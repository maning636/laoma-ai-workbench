# 老马AI工作台 · 开源发布交付口径

> **版本** v1.1　|　**日期** 2026-10-24　|　**对应交付** v1.1.5（Release tag `v1.1.5`）
> **依据** 马哥 2026-10-23 在《开源发布收尾 · 待决表》P1–P7 的 7 项决策；
> 以及客户端发布形态表 D1–D5 的追认（该表 P4=A：「全部按实际落地确认」）。
> **性质** 这是**对外口径**的唯一权威出处 —— 官网文案、README 首屏、客服话术、
> Release 说明一律以本文件为准；本文件与实际不符时以实际为准并改本文件。

---

## 1 一句话

老马AI工作台（Prism-Fusion）以 **AGPL-3.0** 开源，Windows 端交付**单一安装包**
`LaomaAI-1.1.5-setup.exe`（639,437,816 B），**源码走公开 GitHub 仓库**，
**完整版由本地注册码解锁**。

---

## 2 对外下载口径

| 项 | 值 |
|---|---|
| 公开仓库 | https://github.com/maning636/laoma-ai-workbench |
| Release（v1.1.5） | https://github.com/maning636/laoma-ai-workbench/releases/tag/v1.1.5 |
| 安装包 · GitHub 主通道 | https://github.com/maning636/laoma-ai-workbench/releases/download/v1.1.5/LaomaAI-1.1.5-setup.exe |
| 安装包 · 国内镜像兜底 | https://maning789link.top/downloads/LaomaAI-1.1.5-setup.exe |
| 官网 | https://maning789link.top |
| 安装包字节数 | 639,437,816 B（约 610 MiB；官网文案写「约 610 MB」） |
| SHA-512（base64） | `5SE3g3MLWgym+OcYomVkU3BM8U9pIY/a7u++KS1yTpFKS3gzSwWelAAQg6Q/y+LeuAAn6XDxI9bytAPs0vL0FA==` |
| 校验命令 | `Get-FileHash .\LaomaAI-1.1.5-setup.exe -Algorithm SHA512` |

Release 三件套（GitHub 资产、官网链接、磁盘文件同名同大小）：

| 文件 | 字节数 | SHA-256 |
|---|---|---|
| `LaomaAI-1.1.5-setup.exe` | 639,437,816 | `e99fb5bff4ba3b5ea7690b6f7e7e2a5840a14980cf2829c1f7abcfa9b4baad19` |
| `LaomaAI-1.1.5-setup.exe.blockmap` | 650,420 | `3c80f99de6609e69a94e728f0f67e3eb140b7bf534fdbd0fc8b2e60c681a6182` |
| `latest.yml` | 347 | `333c773104dfdcba83ac1ee70e5e75c21a66d8860a22c6f94e2f60df0cbfa987` |

`latest.yml` 内记录的 `size: 639437816` 与 `sha512` 与磁盘、官网展示值三方一致。

**下载速度实测**（2026-10-23 实测，非估算）：

| 通道 | 实测速率 | 639 MB 理论耗时 |
|---|---|---|
| GitHub 直连 | 0.12 MB/s | ≈ 89 分钟 |
| GitHub 走代理 | 2.25 MB/s | ≈ 4.7 分钟 |
| 自建镜像直连 | 0.36 MB/s | ≈ 29 分钟 |

> 官网主按钮指 GitHub Release，旁边挂自建镜像兜底（P1=A 保留现状双通道）。
> **不要在没实测的情况下承诺任何速度数字。**

---

## 3 客户端发布形态 D1–D5（2026-10-23 追认确认）

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

---

## 4 商业与解锁口径

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

## 5 本版明确不做的事

| 不做 | 决策 | 原因 |
|---|---|---|
| 不切 GitHub provider（自动更新） | P3=A | 自动更新走 GitHub 直连 0.12 MB/s → 639 MB 约 89 分钟，对国内用户是净退化 |
| 不升服务器带宽、不上腾讯云 COS | P1=A | 现状双通道保留，0 成本；等真有用户反馈再动 |
| 不在官网公开微信号文字 | P5=B | 防爬号批量加好友 |
| 不做 1.1.4 → 1.1.5 升级安装验收 | P6=C | 本轮只做备份 round18，升级验收暂缓 |
| 不提供 `CLOUD_LLM_API_KEY` / `TIKHUB_API_KEY` | P7=B | 走「功能关掉 + 明确提示」兜底 |

---

## 6 事实来源与复核方式

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

> 凭据（注册码私钥、云端账号密码）**一律不写进本文件、不写进仓库、不进 git**。
