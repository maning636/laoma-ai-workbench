# Community 版打包验证报告（构建 + dir 产物）

- **报告日期**：2026-10-19
- **执行环境**：Windows 10.0.26100 / Node 22 / PowerShell 5.1 / electron-builder 24.13.3 / electron 28.0.0
- **前置依据**：`docs/dev-reports/2026-10-16-community-packaging.md`、`docs/dev-reports/2026-10-16-m5-implementation.md`
- **验证范围**：仅前端 standalone 构建 + electron-builder **dir 模式**打包；**未**执行 NSIS installer 打包（551 MB 耗时过长，超出委派任务边界）。

---

## 0. TL;DR

| 阶段 | 结果 |
|---|---|
| 前端 `npx next build` | ✅ 成功，`prism_frontend/.next/standalone/` = 45.49 MB |
| `build-community.ps1` 语法 | ✅ 通过，8 个参数齐全 |
| `package.community.json` 配置校验 | ❌ **初次失败** → ✅ 修复后通过 |
| `electron-builder --dir` 打包 | ✅ 成功，用时 30.7 s |
| 产物完整性检查 | ✅ 20 项关键资源全部齐全，`dist-community/` = 1.61 GB |
| Pro 版打包配置 | ✅ 未改动，未受影响 |

**关键修复**：把 `desktop-electron/package.community.json` 从 **package.json 风格**（顶层含 `build` 包装层 + npm 元信息）重构为 electron-builder 的**扁平 build 配置**格式，元信息改由 `extraMetadata` 传入。详见 §4。

---

## 1. 前端构建验证

```powershell
cd D:\dim开发\Prism-Fusion\prism_frontend
npx next build
```

### 结果

- **状态**：✅ 成功，无 tsc 错误、无 lint 错误。
- **standalone 输出**：`prism_frontend/.next/standalone/`
  - `server.js` 存在（10.7 KB，Next.js 16 standalone 入口）
  - `.next/static/` 存在（客户端 assets）
  - `public/` 存在
  - **总大小 45.49 MB**
- **route 清单**：M5 图片编辑器页面 `/tools/image-editor` 已随 standalone 一起产出；共 prerendered 29 条 route（`/`、`/publish`、`/fusion/*`、`/easel-*`、`/tools/image-editor` 等）。
- **无 tsc 修复**：`npx next build` 内含 tsc 步骤，一次通过，不需要额外改动。

---

## 2. 打包脚本语法验证

```powershell
$ast = [System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path .\build-community.ps1), [ref]$null, [ref]$null)
$ast.ParamBlock.Parameters.Count
```

- **状态**：✅ 语法正确，无 ParserError。
- **参数（8 个）**：
  - `BuildNumber`（string）
  - `SkipFrontend`（switch）
  - `SkipBackend`（switch）
  - `SkipPrismenv`（switch）
  - `OutputRoot`（string）
  - `KeepWinUnpacked`（switch）
  - `SignInstaller`（switch）
  - `AutoYes`（switch）
- **文件规模**：462 行，UTF-8 with BOM（PowerShell 5.1 兼容）。

---

## 3. `package.community.json` 配置校验（初次失败 + 修复）

### 3.1 初次报错

```
Invalid configuration object. electron-builder 24.13.3 has been initialized
using a configuration object that does not match the API schema.
- configuration has an unknown property 'repository'.
```

**根因**：`electron-builder --config <file>` 加载的是**扁平的 build 配置**，不是完整的 `package.json`。当该文件里出现 `repository`、`name`、`version` 等 npm 元信息字段时，electron-builder 会走"配置校验"路径（`app-builder-lib/src/util/config.ts:240` → `schema-utils`），把它们当未知 build 属性报错。

删除 `repository` 后立刻暴露第二层错误：

```
- configuration has an unknown property 'build'.
```

因为顶层还有 `build` 包装层（Pro 版 `package.json` 结构），`--config` 模式不接受这种嵌套。

### 3.2 与 Pro 版行为差异

Pro 版走 `electron-builder`（无 `--config`），electron-builder 从 `package.json` 中读取，会自动剥离 `name`/`version`/`repository` 等 npm 元信息，只保留 `build` 块作为配置源；因此 Pro 版 `package.json` 里的 `repository` 与 `build` 结构不触发校验错误。

Community 版走 `--config package.community.json`，该文件被直接当"build 配置"用，不能是 package.json 结构。

### 3.3 修复方案

**重构 `desktop-electron/package.community.json`** 为扁平 build 配置：

- 删除顶层 `name` / `version` / `description` / `author` / `license` / `main` / `scripts` / `dependencies` / `devDependencies` / `repository` / `build` 包装层。
- npm 元信息迁入 `extraMetadata`：electron-builder 会在打包时把它们合并到运行时 `app.asar/package.json`，应用可正常 `require('./package.json').version`。
- 顶层直接是 `appId` / `productName` / `executableName` / `directories` / `extraResources` / `win` / `nsis` 等 build 属性。

**修改后顶层 keys**：
```
extraMetadata, appId, productName, executableName, artifactName, asar,
asarUnpack, directories, files, extraResources, win, nsis,
compression, electronVersion, publish
```

**元信息保持**：
- `extraMetadata.name` = `laoma-ai-workbench-community`
- `extraMetadata.version` = `1.1.0-community`
- `extraMetadata.license` = `AGPL-3.0`
- `extraMetadata.main` = `src/main/index.js`

### 3.4 修复后重跑

```powershell
npx electron-builder --config package.community.json --win --x64 --dir
```

```
  • electron-builder  version=24.13.3 os=10.0.26100
  • loaded configuration  file=D:\dim开发\Prism-Fusion\desktop-electron\package.community.json
  • packaging         platform=win32 arch=x64 electron=28.0.0 appOutDir=dist-community\win-unpacked
```

用时 **30.7 s**，无错误。

---

## 4. dir 模式打包结果

**命令**：
```powershell
cd D:\dim开发\Prism-Fusion\desktop-electron
npx electron-builder --config package.community.json --win --x64 --dir
```

**输出目录**：`desktop-electron/dist-community/`
**总大小**：**1.61 GB（1653.1 MB）**

### 4.1 `win-unpacked/` 顶层

| 项 | 大小 | 说明 |
|---|---:|---|
| `LaomaAICommunity.exe` | **168.47 MB** | ✅ executableName 正确 |
| `resources/` | 1379.8 MB | 见 §4.2 |
| `locales/` | 36.1 MB | Electron 内置 i18n |
| `dxcompiler.dll` / `d3dcompiler_47.dll` / `icudtl.dat` 等 | ~60 MB | Chromium runtime |
| `LICENSE.electron.txt` / `LICENSES.chromium.html` | — | 开源许可 |

### 4.2 `win-unpacked/resources/` 分布

| 子项 | 大小 | 备注 |
|---|---:|---|
| `prismenv/` | 652.1 MB | ✅ Python 环境（含 `Scripts/python.exe` 0.23 MB） |
| `services/` | 642.2 MB | ✅ PyInstaller 三 target（backend / celery-worker / automation-worker） |
| `frontend/` | 49.6 MB | ✅ Next.js standalone |
| `prism_backend/` | 30.1 MB | ✅ 后端源码（已剔除 data/cookies/fingerprints/browser_profiles/videoFile/logs/db/backups） |
| `redis/` | 2.5 MB | ✅ redis-server.exe 1.77 MB + cli + conf + EventLog.dll |
| `app.asar` | 1.82 MB | Electron 主进程源码 |
| `tools/` | 1.2 MB | ✅ 7za.exe |
| `supervisor/` | 0.1 MB | ✅ supervisor.py + api_server.py |
| `.env.community.example` | 4.6 KB | ✅ 从 `.env.example` 注入 |
| `scripts/` | — | ✅ `hermes/*.ps1`、`hermes/*.cmd`、`packaging/install_hibbiki_chromium.ps1` |
| `config/` | — | ✅ 从 `../config` 注入 |

### 4.3 PyInstaller 三个 exe（`services/`）

PyInstaller **onedir** 布局（PyInstaller 6.x 默认），非 `dist/backend.exe`：

| exe | 大小 | 位置 |
|---|---:|---|
| `backend.exe` | 26.29 MB | `services/backend/backend.exe` |
| `celery-worker.exe` | 19.6 MB | `services/celery-worker/celery-worker.exe` |
| `automation-worker.exe` | 19.04 MB | `services/automation-worker/automation-worker.exe` |

每个 exe 旁都有 `_internal/` 目录（依赖库 + `python313.dll` 等）。`automation-worker/_internal/patchright/driver/node.exe` = 87.19 MB（patchright 内置 Node.js）。

---

## 5. 关键资源核对清单

| 检查项 | 状态 |
|---|---|
| `executableName = LaomaAICommunity.exe` | ✅ `win-unpacked/LaomaAICommunity.exe`（168.47 MB） |
| `appId = com.laomai.workbench.community` | ✅（配置生效，asar 内 package.json 已注入） |
| `prismenv/` | ✅ 652.1 MB，含 `Scripts/python.exe` |
| `prismenv/Scripts/python.exe` | ✅ 0.23 MB |
| `prism_backend/` | ✅ 30.1 MB（已按 filter 剔除 cookies/fingerprints/db/logs 等） |
| `frontend/standalone/` | ✅ 49.6 MB（server.js + `.next/static` + `public`） |
| `services/backend/backend.exe` | ✅ 26.29 MB |
| `services/celery-worker/celery-worker.exe` | ✅ 19.6 MB |
| `services/automation-worker/automation-worker.exe` | ✅ 19.04 MB |
| `.env.community.example` | ✅ 4.6 KB（内容取自 `../.env.example`） |
| `resources/supervisor/supervisor.py` | ✅ 0.07 MB |
| `resources/redis/redis-server.exe` | ✅ 1.77 MB |
| `resources/tools/7zip/7za.exe` | ✅ 1.17 MB |
| `resources/scripts/hermes/*.ps1` | ✅（仅工具脚本，不含 hermes-agent 代码） |
| `resources/scripts/packaging/install_hibbiki_chromium.ps1` | ✅ |
| `resources/app.asar` | ✅ 1.82 MB |
| `resources/config/` | ✅ 从 `../config` 注入 |

### 5.1 Hermes 未打包确认

Community 版 `extraResources` 中没有 `../tools/hermes-agent`、`../tools/hermes-webui` 两条，Pro 版才有。已核对产物中 **不存在** `resources/tools/hermes-agent/` 或 `resources/tools/hermes-webui/` 目录。

---

## 6. 发现的问题与修复

### 6.1 `package.community.json` 格式不兼容（**已修复**）

- **问题**：初次打包报 `configuration has an unknown property 'repository'`，随后又暴露 `unknown property 'build'`。
- **根因**：`--config <file>` 期望扁平 build 配置，当前文件是完整 package.json 结构。
- **修复**：重构为扁平 build 配置；npm 元信息迁入 `extraMetadata`。
- **影响**：`desktop-electron/package.community.json` 内容完全重写（顶层 202 行 → 196 行）。
- **附带修复**：删除顶层 `repository` 字段（`build.publish.repo` 已指向同一仓库）。

### 6.2 `build-community.ps1` 里可能存在的命令引用问题

`build-community.ps1` 里的 electron-builder 调用形式是：
```powershell
node_modules\electron-builder\cli.js --config package.community.json --win --x64 --dir
```
这与本次验证使用的 `npx electron-builder --config package.community.json ...` 等价。修复后的扁平配置同样适用，脚本无需修改。

### 6.3 Pro 版配置完整性

`desktop-electron/package.json`、`desktop-electron/installer.iss`、`scripts/packaging/build-package.bat`、`scripts/packaging/build-services.ps1` 等 Pro 版文件**未做改动**。`git status` 显示 Community 版新增文件均为未跟踪状态（`?? desktop-electron/build-community.ps1`、`?? desktop-electron/installer-community.iss`、`?? desktop-electron/package.community.json`），Pro 版无 diff。

---

## 7. 剩余不确定性与建议

1. **NSIS installer 打包未验证**：本次仅跑 `--dir`。完整 installer 生成走 Inno Setup 或 electron-builder 内置 NSIS，需再跑一次去掉 `--dir` 才能验证 `老马AI工作台-Community-1.1.0-community-setup.exe` 产物。预计 5-15 分钟（跳过 prismenv/standalone 时）。

2. **`installer-community.iss` 未验证**：脚本内容与 AppId GUID（`{3A7C9D2E-5F4B-4D6E-8B1C-2D3E4F5A6B7C}`）已在配置中确认，但 Inno Setup 编译器未实际运行。若首次跑完整打包失败，Inno Setup 脚本是首要排查对象。

3. ~~`app.asar` 内 package.json 元信息~~ **✅ 已验证**：解包 `win-unpacked/resources/app.asar`，内部 `package.json` 内容：
   ```json
   {
     "name": "laoma-ai-workbench-community",
     "version": "1.1.0-community",
     "description": "老马AI工作台 Community (Open Core, AGPL-3.0)",
     "main": "src/main/index.js",
     "author": "Laihiujin",
     "license": "AGPL-3.0",
     "dependencies": { "electron-log": "^5.0.1", "electron-updater": "^6.8.9" },
     "repository": "https://github.com/Laihiujin/laoma-ai-workbench.git"
   }
   ```
   `extraMetadata` 的 5 个字段（name/version/description/author/license）全部正确注入；`main`/`dependencies`/`repository` 由 electron-builder 从 CWD 的 `package.json` 自动合并。`require('./package.json').name` 在打包后返回 `laoma-ai-workbench-community`，符合预期。

4. **`prism_backend/fingerprints/` 未被打包**：符合 Community 版设计（Persona 指纹是 Pro 特性）。但 `prism_backend` 主代码里如有对 `fingerprints/` 目录的运行时读取，需确认降级路径正确（Community 版应无该分支）。这是代码层验证，非打包层。

5. **`.env.community.example` 编码**：源 `../.env.example` 是 GBK 编码（Windows 中文注释）。产物文件字节完整，但 UTF-8 读取会显示乱码。若安装后用户在 Notepad（Windows 11+ 默认 UTF-8）打开，注释会乱码但 `KEY=VALUE` 行不受影响（都是 ASCII）。**建议**：后续统一把 `.env.example` 转成 UTF-8 with BOM。当前不阻塞。

6. **`build.publish.repo` 与 Pro 版共用**：仍指向 `Laihiujin/laoma-ai-workbench`。若两个版本共用 GitHub Release，`latest.yml` 会互相覆盖。建议后续为 Community 版单独建仓库 `laoma-ai-workbench-community` 或使用 `build.publish.channel: "community"`。

7. **首次全量打包耗时预估 30-45 分钟**：与 Pro 版接近。可通过 `-SkipFrontend -SkipBackend -SkipPrismenv` 加速重打包至 2-3 分钟（本次 `--dir` 部分实测 30.7 s，主要时间在 extraResources 拷贝）。

---

## 8. 用户完整打包命令（生成 NSIS installer）

```powershell
cd D:\dim开发\Prism-Fusion\desktop-electron

# 首次完整打包
.\build-community.ps1

# 或加速重打包（前端 + 后端 + prismenv 已就绪）
.\build-community.ps1 -SkipFrontend -SkipBackend -SkipPrismenv -BuildNumber 1

# 仅重跑 electron-builder + NSIS（最快）
.\build-community.ps1 -SkipFrontend -SkipBackend -SkipPrismenv -BuildNumber 2 -AutoYes
```

**预期产物**：
- `desktop-electron/dist-community/win-unpacked/LaomaAICommunity.exe`（168.47 MB，本报告已验证 ✅）
- `desktop-electron/dist-community/老马AI工作台-Community-1.1.0-community-setup.exe`（本次未生成）
- `desktop-electron/dist-out/community/v1/老马AI工作台-Community-1.1.0-community-setup.exe`（本次未生成）

**跳过 NSIS 的等价命令**（等价于本报告验证的 dir 模式）：
```powershell
npx electron-builder --config package.community.json --win --x64 --dir
```

---

## 9. 修改文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `desktop-electron/package.community.json` | **重写** | 从 package.json 结构改为扁平 build 配置，元信息迁入 `extraMetadata`；顶层删除 `repository` |
| `docs/dev-reports/2026-10-16-community-build-verify.md` | **新增** | 本报告 |

**未改动**（Pro 版完全保留）：
- `desktop-electron/package.json`
- `desktop-electron/installer.iss`
- `desktop-electron/build-community.ps1`（本次验证语法通过，无需修改）
- `desktop-electron/installer-community.iss`（本次未验证 Inno Setup 编译）
- `scripts/packaging/*`

---

## 10. 相关文件

- [package.community.json](../../desktop-electron/package.community.json) — Community 版 electron-builder 扁平配置（本次修复）
- [build-community.ps1](../../desktop-electron/build-community.ps1) — 打包脚本（语法已通过）
- [installer-community.iss](../../desktop-electron/installer-community.iss) — Inno Setup（AppId 已独立，未编译验证）
- [2026-10-16-community-packaging.md](2026-10-16-community-packaging.md) — 上游设计报告
