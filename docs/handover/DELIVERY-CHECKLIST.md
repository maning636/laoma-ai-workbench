# 交付确认单 · 老马AI工作台（Prism-Fusion）接收确认

> **用途**：接手工作组逐项核对，确认「拿到了什么、理解了什么、能复跑什么」。
> **要求**：C 组（事实核对）**必须自己跑一遍命令**，不能只签字 —— 这是本项目的一贯要求（见 `AGENT.md` 与主文档 §8）。
> 交回方式：把本文件勾好发回，或在对应位置写「已核对 + 日期」。

---

## A 组 · 接收确认（材料是否到手）

| # | 项 | 位置 / 地址 | 状态 |
|---|---|---|---|
| A1 | 公开仓库可访问 | `https://github.com/maning636/laoma-ai-workbench` | □ 已确认 |
| A2 | Release `v1.1.5` 可访问 | `/releases/tag/v1.1.5` | □ 已确认 |
| A3 | 3 个 Release 资产齐全 | `.exe` / `.exe.blockmap` / `latest.yml` | □ 已确认 |
| A4 | 官网可访问 | `https://maning789link.top` | □ 已确认 |
| A5 | 官网下载链接可点 | 首页「客户端下载」区 | □ 已确认 |
| A6 | 国内镜像下载可点 | `https://maning789link.top/downloads/LaomaAI-1.1.5-setup.exe` | □ 已确认 |
| A7 | 主交接文档已读 | `docs/handover/PROJECT-HANDOVER.md` | □ 已读 |
| A8 | 交付确认单已读 | 本文件 | □ 已读 |

---

## B 组 · 环境与访问（能不能干活）

| # | 项 | 要求 | 状态 |
|---|---|---|---|
| B1 | 代码已 clone | 工作区完整，`git log -1` 能跑 | □ 已完成 |
| B2 | 代码基线正确 | `git rev-parse --short HEAD` = `6af4768` | □ 已核对 |
| B3 | 三个 remote 都在 | `origin` / `upstream` / `prism-server` | □ 已核对 |
| B4 | Python 3.11+ | 项目要求 `>=3.11` | □ 已确认 |
| B5 | Node **22** | **硬性下限**，Node 20 会让 6 个 DOM 测试全挂 | □ 已确认 |
| B6 | 前端依赖装好 | `cd prism_frontend && npm ci` | □ 已完成 |
| B7 | 缓存落 D 盘 | npm/pip/TEMP/PyInstaller 缓存**严禁写 C 盘** | □ 已配置 |
| B8 | 本地能起后端 | `scripts\launchers\start_stack_prismenv.bat` | □ 已跑通 |
| B9 | 本地能起前端 | `scripts\launchers\start_frontend.bat` | □ 已跑通 |
| B10 | 服务器访问权限 | SSH key 可用（**不要在文档/提交里出现 key 内容**） | □ 已确认 |
| B11 | 知道哪些服务不能碰 | `payskill`（8090）/ `fde-api`（8787）/ MariaDB（3306）/ Redis（6379）**同机其它业务共用** | □ 已确认 |

---

## C 组 · 事实核对（**必须自己跑一遍**）

> 每条都给了可复跑命令。跑不通说明环境有问题，先解决再往下走。

### C1 · 代码基线三处一致

```powershell
git -C 'D:\dim开发\Prism-Fusion' rev-parse --short HEAD          # 期望 6af4768
git -C 'D:\dim开发\Prism-Fusion' rev-parse --short origin/main     # 期望 6af4768
```

### C2 · 安装包字节数与三方对账

```powershell
# 期望：磁盘 / GitHub / latest.yml 三方一致 = 639,437,816 B
Get-Item 'D:\dim开发\Prism-Fusion\desktop-electron\dist-out\v5\LaomaAI-1.1.5-setup.exe' | Select-Object Length
Get-Content 'D:\dim开发\Prism-Fusion\desktop-electron\dist-out\v5\latest.yml' -Encoding UTF8
```

### C3 · 备份清单可回读校验

```powershell
$env:PYTHONIOENCODING='utf-8'
& 'D:\dev\python\python.exe' 'D:\dim开发\Prism-Fusion\scripts\backup\build_backup_manifest.py' `
  --backup-root 'D:\Prism-Fusion-Backup' --verify
# 期望输出：通过 14 个，不符/缺失 0 个
```

### C4 · 验收清单可重建、可回读

```powershell
& 'D:\dev\python\python.exe' 'D:\dim开发\Prism-Fusion\scripts\docs\build_client_acceptance_checklist.py'
& 'D:\dev\python\python.exe' 'D:\dim开发\Prism-Fusion\scripts\docs\read_client_acceptance_checklist.py'
# 期望：items 41 / problems 0 / pending 41
```

### C5 · CI 八硬门是绿的

```powershell
& 'D:\dev\python\python.exe' 'D:\cache\tmp\_gh_ci_new.py' 6af4768 2400
# 或直接看 https://github.com/maning636/laoma-ai-workbench/actions
# 期望：head=6af4768 的 run 全 success（E2E packaged 按预期 skipped）
```

### C6 · 云端服务在跑

```powershell
$key = 'D:\dim开发\Prism-Fusion\_deploy_inputs\ssh\prism_deploy_ed25519'
$opts = @('-i', $key, '-o', 'StrictHostKeyChecking=no', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15')
& ssh @opts 'root@101.43.65.216' 'systemctl is-active prism-cloud; curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8091/health'
# 期望：active + 200
```

### C7 · 判档模型你讲得清

| 检查 | 你的回答 |
|---|---|
| 「完整版」由什么决定？ | |
| 本地注册码和云端订阅，谁决定账号数上限？ | |
| 云端订阅还有哪 7 项 flag 的决定权？ | |
| 为什么 P7 不把订阅体系一起关掉？ | |
| `unknown` 和 `unavailable` 的区别是什么？为什么必须分开？ | |

> 最后一问是 P7 的核心设计，答不上说明没读 §4.1，请回去重读。

### C8 · 平台能力表你核过

- 后端真正有发布工具的平台是哪些？（§1.3）
- 前端向导多列了哪 3 个后端不支持的平台？
- 你是否理解这属于**待修缺口**而不是「设计如此」？

> 参考命令：
> `Select-String -Path 'prism_backend\fastapi_app\services\publish_tools\__init__.py' -Pattern '_PLATFORM_MODULES' -Context 0,4`

---

## D 组 · 坑清单掌握度（自测）

> 主文档 §8 共 8 组坑。**请标出你觉得自己还会踩的**，写进下面的表 —— 我据此决定要不要给你加急培训。

| 组 | 主题 | 我最可能踩的一条 | 需要培训 |
|---|---|---|---|
| G1 | Git 与推送 | | □ |
| G2 | CI 与测试 | | □ |
| G3 | Windows / PowerShell | | □ |
| G4 | 打包与发布 | | □ |
| G5 | 运维与服务器 | | □ |
| G6 | 代码与验证方法论 | | □ |
| G7 | 架构与业务逻辑 | | □ |

**必答三题**：

| # | 问题 | 你的回答 |
|---|---|---|
| D1 | 推 origin 前为什么必须先探两条链路？（G1） | |
| D2 | 为什么本地 Windows 全绿 CI 还会红？（C1/C2） | |
| D3 | 内存不足时打包会报什么错？该不该硬扛？（W12） | |

---

## E 组 · 接手任务认领

> 从主文档 §6 选。标了「需放行」的先不要动手。

| # | 任务 | 认领人 | 计划完成 | 备注 |
|---|---|---|---|---|
| E1 | 前端向导平台列表对齐后端（§6.2-2） | | | |
| E2 | `release.yml` tag 流程首次实跑验证（§6.2-3）⚠️ 严禁手动 dispatch | | | |
| E3 | 补仓库社区文件（§6.2-4） | | | |
| E4 | 备份 round18 收尾（§6.2-5） | | | |
| E5 | 补 dev-reports 收官报告（§6.2-6） | | | |
| E6 | 1.1.6 重打包（§6.1-1）**需放行** | | | |

---

## F 组 · 工作纪律确认（逐条打勾表示接受）

| # | 纪律 | 接受 |
|---|---|:---:|
| F1 | 提交前跑 `git status --short`，确认没有运行时/敏感文件进 index | □ |
| F2 | **不用** `git add -A` / `git add .`，逐个显式 add | □ |
| F3 | **不用** stash / `reset --hard` / `checkout ./` / `clean` / force push / `--no-verify` | □ |
| F4 | commit message **不包含**本机绝对路径、账号标识、cookie、代理 IP | □ |
| F5 | 凭据（注册码私钥、云端账号密码、服务器 env）**一律不进仓库、不进文档、不进 issue/PR** | □ |
| F6 | 改中文文件后**必须扫 U+FFFD 乱码**再收工 | □ |
| F7 | `.ps1` / `.bat` 保持纯 ASCII（`.bat` 还要 CRLF） | □ |
| F8 | 本地通过 ≠ CI 通过，**以 GitHub run 结果为准** | □ |
| F9 | 验证「改写/覆盖的那条路径」时，用**只有它能产生的值**，不能用默认值 | □ |
| F10 | 不擅自改已拍板的决策（P1–P7 / D1–D5 / 单一客户端 / 支付删除 / 注册码∩订阅） | □ |
| F11 | 不擅自启动 1.1.6 打包（等放行） | □ |
| F12 | 涉及对外可见的动作（发 Release、改官网）先确认再动 | □ |

---

## G 组 · 回执

| 项 | 内容 |
|---|---|
| 工作组 / 团队名 | |
| 接收人 | |
| 接收日期 | |
| A/B/C 组全部通过 | □ 是　□ 否（列出未通过项：　　　　　　　　　） |
| 需要立即澄清的问题 | |
| 期望的第一个产出 | |
| 需要马哥决策的事项 | |

---

**交回方式**：本文件勾好后发回；或直接在仓库里提 issue 引用本文件编号。
**交回后我会做的**：按 §6 排期推进；F 组有未接受项的，暂不派活。
