# 打包与发布

本文档覆盖桌面版的一键打包、产物位置、版本号和 CI 发布流程。启动/开发走 [STARTUP.md](STARTUP.md)，本文只讲"打包"。

---

## 1. 一键打包（本地）

在仓库根目录执行：

```bat
scripts\packaging\build-package.bat
```

想全自动跑（CI 式、不弹"选择打包类型"），加环境变量：

```bat
set LAOMA_AUTO_YES=1
set LAOMA_PACKAGE_TYPE=2          :: 1=NSIS, 2=Inno Setup(默认), 3=只出 win-unpacked 目录
scripts\packaging\build-package.bat
```

### 7 阶段流程

脚本按顺序做（对应控制台 `[x/7]` 提示）：

1. **Sanitize release workspace** — 调 `scripts\release\prepare-release.ps1`，把上次构建残留清干净。
2. **准备 packaged prismenv + Hermes 运行时** — 若 `prismenv\Scripts\python.exe` 不存在就 `python -m venv prismenv`；升级 pip；`pip install -r requirements.txt`；卸载冲突的 `playwright`；再装 `pyinstaller psutil patchright==1.59.1`；跑 `scripts\hermes\setup-local-hermes.ps1` 拉 Hermes agent + WebUI，落盘 `.hermes-runtime-ready` 标记。
3. **PyInstaller 后端** — `scripts\packaging\build_services.ps1` 用 packaged prismenv 打 `backend`、`celery-worker`、`automation-worker` 三个 onedir 包，产物在 `dist\services\`。
4. **停进程** — 检查 `LaomaAI.exe` / `supervisor.exe` 是否在跑，杀掉可能锁住 `dist-build` 的服务进程。
5. **校验 Supervisor** — 找 `build\supervisor\supervisor.exe` 或 `dist\supervisor.exe`；缺失只 WARN 不阻塞（可用 `desktop-electron\scripts\prepare-supervisor-build.bat` 补）。
6. **读版本号 + 清旧产物 + 前端 build** — 读 `scripts\packaging\build-version.json`，`FULL_VERSION = <version>.<buildNumber>`；清 `desktop-electron\dist-build\win-unpacked` 和 `*.exe`；`cd prism_frontend && npm run build`（要求 `.next\standalone\server.js` 存在，即 `output: 'standalone'`）。
7. **electron-builder + 安装器** — `electron-builder --win --x64 --dir` 出 `win-unpacked`，然后把 prismenv / browsers / services / prism_backend / hermes-agent / hermes-webui 都 xcopy/robocopy 进 `resources\`；移到 `dist-out\v<buildNumber>\win-unpacked\`；再按选择跑 NSIS 或 Inno Setup（默认 Inno）。

---

## 2. 产物

产物统一在 `desktop-electron\dist-out\v<buildNumber>\` 下（`<buildNumber>` 来自 `build-version.json`，不是版本号的最后一节）：

| 类型 | 路径 |
|---|---|
| 未打包目录（快速调试用） | `desktop-electron\dist-out\v<buildNumber>\win-unpacked\` |
| Inno Setup 安装器（默认） | `desktop-electron\dist-out\v<buildNumber>\老马AI工作台-Setup-v<version>.exe` |
| NSIS 安装器（可选） | `desktop-electron\dist-out\v<buildNumber>\*.exe`（由 electron-builder 产出） |

`dist-out\v<buildNumber>\win-unpacked\resources\` 里关键目录：

- `prismenv\` — 内嵌 Python venv（含 `Scripts\python.exe`、Hermes runtime 标记）。
- `browsers\` — patchright/chromium 浏览器二进制。
- `services\` — PyInstaller 三个后端 exe（`backend_service`、`celery_worker_service`、`automation_worker_service`，onedir 形式）。
- `prism_backend\` — robocopy 复制的后端源码（已排除用户数据，见 §5）。
- `tools\hermes-agent\`、`tools\hermes-webui\` — Hermes agent 和 WebUI。
- `supervisor\` — `supervisor.exe` / `supervisor.py` / `api_server.py`。
- `redis\` — Redis Windows 二进制。

---

## 3. 版本号管理

版本号单一来源：[`scripts\packaging\build-version.json`](scripts/packaging/build-version.json)

```json
{"version": "1.1.0", "buildNumber": 1, "lastBuildDate": "2026-10-11"}
```

- `version` — 语义版本，写进 `electron-builder` 的 `extraMetadata.version` 和 Inno Setup 文件名。
- `buildNumber` — 每次打包 +1，决定输出目录 `dist-out\v<buildNumber>` 和 `buildVersion=<version>.<buildNumber>`。
- `lastBuildDate` — 记录最近一次构建日期，供人查。

改版本前**手动**改这个 JSON；`build-package.bat` 只读，不会自动 +1。CI 场景走 `.github\workflows\release.yml`，版本由 git tag `v<X.Y.Z>` 决定，会覆盖 `desktop-electron\package.json` 的 `version`。

---

## 4. CI 发布

配置在 [`.github\workflows\release.yml`](.github/workflows/release.yml)。

**触发方式**

- push tag `v<X.Y.Z>`：自动把 `desktop-electron/package.json` 的 `version` 同步为 `<X.Y.Z>`。
- `workflow_dispatch` 手动：填 `version` 输入则同步；留空用 `package.json` 现有版本。

**3 个 job**

1. `build-windows` — `windows-latest`，Node 22 + Python 3.11：
   - 构建前端（Next.js standalone）
   - 建 `prismenv` 装依赖
   - PyInstaller 打 `supervisor.exe`（`build/supervisor.spec`），复制到 `desktop-electron/resources/supervisor/`
   - 下载 `tporadowski/redis` Windows 二进制到 `desktop-electron/resources/redis/`
   - `electron-builder --win --x64 --publish never`
   - `node scripts/verify-release-assets.mjs` 校验产物
   - 上传 `prism-win-assets`（`*.exe` / `*.exe.blockmap` / `latest.yml`）
2. `build-macos` — `macos-latest`，同样 Node 22 + Python 3.11：
   - 前端 build + prismenv
   - `electron-builder --mac --publish never`（默认 unsigned，Gatekeeper 需要右键打开；配置 `CSC_LINK` / `CSC_KEY_PASSWORD` / `APPLE_ID` 等 GitHub Secrets 可签名公证）
   - 上传 `prism-mac-assets`（`*.dmg` / `*.zip` / `latest-mac.yml` / blockmap）
3. `publish` — `ubuntu-latest`，`needs: [build-windows, build-macos]`：
   - 拉两个 artifact 到 `.release-assets/{win,mac}`
   - 用 `ncipollo/release-action@v1` 发到 GitHub Releases（`allowUpdates: true`、`makeLatest: true`）
   - 资产名与 tag 保持一致

**macOS 签名 Secrets**（可选，装了自动启用）

- `CSC_LINK`、`CSC_KEY_PASSWORD` — 签名
- `APPLE_ID`、`APPLE_APP_SPECIFIC_PASSWORD`、`APPLE_TEAM_ID` — 公证

---

## 5. Secret / 用户数据打包策略

打包时**必须**把这些排除，否则会打进安装器或 CI artifact：

| 类别 | 文件 / 目录 | 处理方式 |
|---|---|---|
| Python 本地配置 | `.env`、`.env.local` | robocopy 排除（源码里本来就不提交） |
| Hermes 凭据 | `auth.json`、`hermes_agent.toml`、`llm_config.toml` | 不进 `extraResources`；`tools/hermes-home` 不被 electron-builder 打 |
| 证书 | `*.pem`、`*.p12` | 不提交，不进包 |
| 用户运行数据 | `prism_backend/browser_profiles`、`cookiesFile`、`fingerprints`、`videoFile`、`logs`、`backups` | `robocopy /XD` 排除（见 `build-package.bat` 里的 robocopy 调用和 `scripts\packaging\build_exclude.txt`） |
| 本地缓存 | `__pycache__`、`.pytest_cache`、`tests`、`*.db`、`*.sqlite` | 同上排除 |

`build-package.bat` 里 robocopy 排除 prism_backend 的完整命令可当参考模板：

```bat
robocopy "%PROJECT_ROOT%prism_backend" "%UNPACKED_RES%\prism_backend" /E /NFL /NDL /NJH /NJS ^
  /XD "__pycache__" ".pytest_cache" "tests" "logs" "backups" "browser_profiles" "videoFile" "cookiesFile" "fingerprints" ^
  /XF "*.pyc" "*.pyo" "test_*" "*.db" "*.db-*" "*.sqlite" "*.sqlite-*" "frontend_accounts_snapshot.json"
```

> **注意**：supervisor 运行时依赖 `resources\tools\hermes-home\` 存在（放 Hermes 凭据），但 `build-package.bat` **不会**打这个目录——它是本地用户配置产物。所以首次安装后，用户在 UI 里走一遍 Hermes 配置流程，把 `auth.json` 落进 `tools\hermes-home\`，之后才能跑 Hermes 相关功能。

---

## 6. 目录约定

- `desktop-electron/resources/supervisor/` — 源码 + 构建产物都放这里：`supervisor.py`、`supervisor.exe`、`api_server.py`。`build/supervisor.spec` 输出到 `dist/supervisor/supervisor.exe`，本地/CI 都会复制到 `resources/supervisor/`。
- `dist/services/` — PyInstaller onedir 后端 exe：`backend_service`、`celery_worker_service`、`automation_worker_service`（由 `scripts\packaging\build_services.ps1` 生成，`PACKAGING_TARGETS` 环境变量可控）。
- `dist/specs/` — PyInstaller `.spec` 中间产物，自动生成，**不入 git**（已在 `.gitignore`）。
- `desktop-electron/dist-build/` — electron-builder 中间产物，每次打包前清。
- `desktop-electron/dist-out/v<buildNumber>/` — 最终产物归档。

---

## 7. 故障排查

| 现象 | 处理 |
|---|---|
| `supervisor.exe` 找不到 / 阶段 2 警告 | 先跑 `desktop-electron\scripts\prepare-supervisor-build.bat`，它会调 PyInstaller 打 `build\supervisor.spec` 并复制到 `resources\supervisor\`。 |
| 阶段 0.25 报 `patchright` 版本不对 | 删掉 `prismenv\.hermes-runtime-ready` 后重跑；`build-package.bat` 会重装 `patchright==1.59.1`。 |
| 阶段 6 报 `node_modules missing` | 先 `cd prism_frontend && npm install`（或 `npm ci`），再跑打包。 |
| Inno Setup 找不到，回落到 NSIS | 装 Inno Setup 6.x（提供 `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`）。 |
| PyInstaller 后端 exe 缺 | 手动 `powershell -ExecutionPolicy Bypass -File scripts\packaging\build_services.ps1`；确保 `prismenv` 已装 `pyinstaller`。 |
| `win-unpacked` 拷不进去 / 文件被锁 | 先 `taskkill /F /IM LaomaAI.exe supervisor.exe` 和三个服务 exe；`build-package.bat` 阶段 1 会自动杀，但如果残留后台进程还是要手动清。 |
| 打包产物里有 `.env` / `auth.json` | 检查 `scripts\packaging\build_exclude.txt` 和 `build-package.bat` 里的 robocopy `/XF`、`/XD`，看是否漏了模式。 |
| CI 上传 asset 404 | 检查 `node scripts/verify-release-assets.mjs` 的报错；通常是版本号没同步或 `extraResources` 缺文件。 |

---

## 8. 参考

- 开发启动流程见 [STARTUP.md](STARTUP.md)
- 打包脚本：[`scripts\packaging\build-package.bat`](scripts/packaging/build-package.bat)
- 后端 PyInstaller：[`scripts\packaging\build_services.ps1`](scripts/packaging/build_services.ps1)
- 版本号：[`scripts\packaging\build-version.json`](scripts/packaging/build-version.json)
- CI 发布：[`.github\workflows\release.yml`](.github/workflows/release.yml)
