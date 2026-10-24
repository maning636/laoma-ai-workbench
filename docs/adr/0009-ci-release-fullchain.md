# ADR-0009: CI 全链路发版 + 体积下限守卫 + SKIP_OBFUSCATE 口径

- **状态**：已接受（补录）
- **日期**：2026-10-24
- **决策者**：工作组
- **证据分级**：【已验证】

---

## 背景

2026-10-24 收官冲刺中，`release.yml` tag 触发的 CI 曾产出「空壳包」——包内不含三后端服务（FastAPI 主服务、Celery worker、patchright browser 服务）的 PyInstaller 编译产物。原因：CI 环境本地没装 PyInstaller 依赖，`SKIP_OBFUSCATE=1` 被误用作绕过 PyArmor 混淆的开关，同时把 PyInstaller 编译也跳过了。

**证据**：
- `docs/handover/PROJECT-HANDOVER.md` §3 阶段 D3、§7.1 第 4 项「release.yml tag 触发分支从未实跑」
- `git show --stat b98c95d`：ci(release): 补齐三后端服务 PyInstaller 构建 + 安装包体积下限守卫——修 CI 空壳包
- `.github/workflows/release.yml:329`

## 决策

**CI 全链路发版补齐三后端 PyInstaller 构建 + 安装包体积下限守卫**：

1. `release.yml` 显式安装 PyInstaller、PyArmor，跑后端编译
2. `SKIP_OBFUSCATE=1` **仅**用于跳过 PyArmor 混淆，**不得**跳过 PyInstaller 编译（编译是必需，混淆是可选）
3. 加体积下限守卫：安装包 < 阈值时 CI 直接失败

**具体落地**：
- `b98c95d`：ci(release): 补齐三后端服务 PyInstaller 构建 + 安装包体积下限守卫
- `538159c`：Release 已存在时跳过重打包（防覆盖已发布资产）
- `f5e8bd5`：Windows 打包后补 `latest.yml` 生成步骤——修测试 tag 验出的 verify 必红缺陷
- 安装包体积下限守卫：`desktop-electron/scripts/verify-release-assets.py`（体积阈值约 500 MB）

**`SKIP_OBFUSCATE` 口径**：
- ✅ 允许：跳过 PyArmor 混淆（开发期快速迭代、PyArmor 授权受限）
- ❌ 禁止：借此跳过 PyInstaller 编译（会导致 CI 空壳包）
- 生产发布必须 `SKIP_OBFUSCATE=0`（走 PyArmor）

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| CI 走本地构建脚本（`build-package.bat`） | CI 是 Linux，无法直接跑 Windows 批处理 |
| 让 CI 只做源码发布，安装包本地手动上传 | 手动上传无版本追溯；且 AGPL 义务要求「提供对应源码」需 CI 证据 |
| `SKIP_OBFUSCATE` 同时跳过 PyInstaller | 已导致空壳包事故（`b98c95d` 修复） |
| 体积下限改为上限 | 上限会导致误报（大版本升级体积增长是合理的） |
| 完全放弃 PyArmor | Pro 版核心资产保护依赖 PyArmor；OSS 版不需要 |

## 代价

**收益**：
- CI 全链路可产出可发布的三后端服务 + 客户端安装包
- 体积下限守卫防止 CI 空壳包
- `SKIP_OBFUSCATE` 语义清晰（仅跳混淆不跳编译）

**代价**：
- CI 运行时间增加（PyInstaller 编译约 3–5 分钟）
- PyArmor 授权需在 CI 上配置（GitHub Secrets）
- 体积下限守卫阈值需随版本调整（每次升级后手动更新）

**已知副作用**：
- 首次跑 `release.yml` tag 触发前，需用测试 tag 验证（`docs/handover/PROJECT-HANDOVER.md` §6.2 第 3 条）
- **严禁手动 dispatch** `release.yml`（可能产出非预期版本）

## 未来复审触发条件

- PyArmor 授权到期或替换为其他混淆方案
- 三后端服务精简或拆分（体积下限守卫阈值需重估）
- 引入容器化构建（Docker-in-Docker）替代本地 PyInstaller

## 参考

- `docs/handover/PROJECT-HANDOVER.md` §3 阶段 D3、§6.2 第 3 条、§7.1 第 4 项
- `.github/workflows/release.yml`
- `desktop-electron/scripts/verify-release-assets.py`
- Commit: `b98c95d` `538159c` `f5e8bd5`
