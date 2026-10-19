# Community 版打包报告

- **报告日期**:2026-10-19
- **上游依据**:`docs/dev-reports/2026-10-16-open-core-strategy.md`、`docs/dev-reports/2026-10-16-open-core-implementation.md`、`docs/dev-reports/2026-10-16-m5-implementation.md`
- **任务目标**:为 Prism-Fusion Community Edition(AGPL-3.0 开源免费版)提供独立打包配置 + 打包脚本,与既有 Pro 版打包并行,允许两版本共存分发。

---

## 1. Community 版功能边界(打包相关)

**包含**(与 Pro 版同源):
- 前端(Next.js 16 standalone):首页 / 素材 / 发布 / 排期 / 图片编辑器(M5)/ 工作流(M4)/ 系统设置 / 注册登录
- 后端(FastAPI):账号管理 / 素材 / 发布任务 / Celery worker / 浏览器自动化(patchright 直连)
- 桌面壳(Electron 28.0.0):Supervisor / Redis / 前后端服务管理
- Open Core feature gate(仅客户端提示,不做付费解锁):3 账号 / 3 平台
- `.env.community.example`(自配 LLM key 提示)

**不包含**(Pro 版专属):
- Hermes Agent / Hermes WebUI(付费 AI 内核)
- C18 代码混淆(pyarmor)
- 云端 prompt 模板配置(打包时不携带任何 prompt 表数据)
- Persona 指纹增强(Inno Setup 中未创建 `fingerprints/` 目录)
- Pro 版专属的 `fingerprints/` 数据目录

**打包差异**:
- AppId 不同 → NSIS/Inno 卸载独立,不冲突
- productName / executableName 均带 "Community" 后缀
- electron-builder 输出目录独立(`dist-community/`)
- 最终产物目录独立(`dist-out/community/v{N}/`)

---

## 2. 现有打包配置摸底

| 项 | 位置 | 说明 |
|---|---|---|
| Electron 主配置 | `desktop-electron/package.json` | Pro 版 `build` 字段,写死 appId=`com.laomai.workbench`、output=`dist-build`、executableName=`LaomaAI` |
| Inno Setup 主脚本 | `desktop-electron/installer.iss` | AppId GUID 硬编码 `8B5F4B5E-...`,与 Pro 版绑定 |
| 打包脚本(Pro) | `scripts/packaging/build-package.bat` | 8 步流程:prismenv → Hermes → PyInstaller → electron-builder → Inno Setup |
| 后端打包 | `scripts/packaging/build_services.ps1` | PyInstaller 三 target:`backend`/`celery-worker`/`automation-worker`,支持 `PACKAGING_TARGETS`/`SKIP_OBFUSCATE` env |
| 版本文件 | `scripts/packaging/build-version.json` | `{version:1.1.0, buildNumber:1}` |
| 前置清理 | `scripts/release/prepare-release.ps1` | 清 dist-build/dist-out/dist 等 |
| 产物校验 | `desktop-electron/scripts/verify-release-assets.mjs` | 校验 exe/blockmap/latest.yml |
| 元数据收尾 | `desktop-electron/scripts/finalize-windows-release.mjs` | 生成 blockmap + latest.yml |

**关键约束**:
- `electron-builder` 支持 `--config <file>` 传入独立配置文件(不改 `package.json` 默认)
- `installer.iss` 的 AppId GUID 是**唯一强区分点**(两版本 AppId 不同才能共存)
- `build_services.ps1` 支持 `SKIP_OBFUSCATE=1` 环境变量跳过 C18 混淆

---

## 3. Community 版新增文件清单

| 文件 | 用途 |
|---|---|
| `desktop-electron/package.community.json` | Community 版 Electron + electron-builder 独立配置(不覆盖 `package.json`) |
| `desktop-electron/installer-community.iss` | Community 版 Inno Setup 脚本(AppId GUID 不同) |
| `desktop-electron/build-community.ps1` | Community 版完整打包脚本(PowerShell) |
| `scripts/packaging/build-version-community.json` | Community 版独立版本号(与 Pro 版 `build-version.json` 分离计数) |

**Pro 版原有文件完全未改动**:`desktop-electron/package.json`、`desktop-electron/installer.iss`、`scripts/packaging/build-package.bat`、`scripts/packaging/build-version.json`、`desktop-electron/scripts/*` 均保留原样。

---

## 4. Community 版配置关键差异

### 4.1 `package.community.json`(Electron)

| 字段 | Community | Pro |
|---|---|---|
| `name` | `laoma-ai-workbench-community` | `laoma-ai-workbench` |
| `version` | `1.1.0-community` | `1.1.0` |
| `license` | `AGPL-3.0` | `Apache-2.0` |
| `build.appId` | `com.laomai.workbench.community` | `com.laomai.workbench` |
| `build.productName` | `老马AI工作台 Community` | `老马AI工作台` |
| `build.executableName` | `LaomaAICommunity` | `LaomaAI` |
| `build.artifactName` | `老马AI工作台-Community-${version}-setup.${ext}` | `老马AI工作台-${version}-setup.${ext}` |
| `build.directories.output` | `dist-community` | `dist-build` |
| `build.nsis.shortcutName` | `老马AI工作台 Community` | `老马AI工作台` |

**extraResources 精简**:
- ✅ 保留:`prismenv`、`prism_backend`、`frontend/standalone`、`config`、`scripts/hermes`(仅工具脚本,不含 hermes-agent 代码)、`scripts/packaging/install_hibbiki_chromium.ps1`
- ✅ 保留(win):`resources/supervisor`、`resources/redis`、`../dist/services`、`node_modules/7zip-bin`
- ❌ 移除:`tools/hermes-agent`、`tools/hermes-webui`(Pro 付费内核)
- ➕ 新增:`../.env.example` → `.env.community.example`(安装后随包发布)

### 4.2 `installer-community.iss`

- **AppId GUID**:`{3A7C9D2E-5F4B-4D6E-8B1C-2D3E4F5A6B7C}`(与 Pro 版 `{8B5F4B5E-9A2C-4D3E-8F1A-6C7D8E9F0A1B}` 不同)
- **AppName**:`老马AI工作台 Community`
- **AppExeName**:`LaomaAICommunity.exe`
- **OutputBaseFilename**:`老马AI工作台-Community-Setup-v{version}`
- **CloseApplicationsFilter**:`LaomaAICommunity.exe`(卸载时精确匹配)
- **AppData 目录**:`{userappdata}\老马AI工作台 Community\data`(与 Pro 版隔离)
- **未创建目录**:`{app}\resources\prism_backend\fingerprints`(Persona 指纹是 Pro 特性)
- **URL**:`MyAppURL` 指向 GitHub 仓库,便于 Community 用户反馈

---

## 5. 打包脚本设计

### 5.1 `build-community.ps1` 参数

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `-BuildNumber` | string | 从 `build-version-community.json` 读 | 覆盖 build number |
| `-SkipFrontend` | switch | false | 跳过 Next.js 构建(假设 `.next/standalone` 已就绪) |
| `-SkipBackend` | switch | false | 跳过 PyInstaller(假设 `dist/services` 已就绪) |
| `-SkipPrismenv` | switch | false | 跳过 prismenv 依赖安装 |
| `-OutputRoot` | string | `desktop-electron/dist-out/community` | 覆盖输出根目录 |
| `-KeepWinUnpacked` | switch | false | 保留 win-unpacked 目录(便于不重装调试) |
| `-SignInstaller` | switch | false | 启用签名(占位) |
| `-AutoYes` | switch | false | CI 模式,末尾不 pause |

### 5.2 8 步流水线

```
[1/8] 停止占用 Community 产物的进程(LaomaAICommunity.exe / supervisor.exe / redis-server.exe)
      - 仅杀来自 dist-out/community/ 或 dist-community/ 或 dist/services/ 路径的进程
      - 不影响用户 dev 环境的 prism_backend 服务

[2/8] 清理旧产物
      - 清 desktop-electron/dist-community(electron-builder 输出)
      - 清 desktop-electron/dist-out/community(最终产物)
      - 清 dist/services(仅当未 SkipBackend)
      - **不触碰** Pro 版 dist-build / dist-out / prismenv

[3/8] 准备 prismenv(Community 依赖)
      - 复用同一个 prismenv/(避免维护两套 Python)
      - 卸载 playwright(与 patchright 冲突)
      - 装 pyinstaller + psutil + patchright==1.59.1
      - 校验 patchright 版本
      - 写入 .community-ready 标记

[3.5] 跳过 Hermes 准备(Community 版无 Hermes,打印 SKIP)

[4/8] 后端打包(PyInstaller)
      - 调用 scripts/packaging/build_services.ps1(与 Pro 复用)
      - 强制 SKIP_OBFUSCATE=1(Community 不混淆)
      - PACKAGING_PYTHON 指向当前 prismenv

[5/8] 前端构建(Next.js standalone)
      - cd prism_frontend && npm run build
      - 校验 .next/standalone/server.js 存在

[6/8] Electron --dir 打包(win-unpacked)
      - node_modules\electron-builder\cli.js --config package.community.json --win --x64 --dir
      - --config.extraMetadata.version=1.1.0-community
      - --config.buildVersion=1.1.0.{buildNumber}
      - 校验 LaomaAICommunity.exe 存在

[7/8] 生成 NSIS 安装包
      - 同 6/8 但去掉 --dir,让 electron-builder 生成 exe
      - 输出:老马AI工作台-Community-1.1.0-community-setup.exe

[8/8] 组织最终产物到 dist-out/community/v{N}/
      - 移动 exe + .blockmap + latest.yml
      - 可选保留 win-unpacked(KeepWinUnpacked)
```

### 5.3 关键设计决策

1. **独立配置文件而非改 package.json**:通过 `--config` 参数,electron-builder 使用 `package.community.json`,不覆盖 Pro 版打包能力。
2. **共用 prismenv**:Community 与 Pro 版后端依赖几乎相同,共用同一个 virtualenv 节省空间;通过 `.community-ready` 文件标记区分。
3. **共用 build_services.ps1**:PyInstaller 后端打包逻辑与 Pro 完全一致(都是打 `backend`/`celery-worker`/`automation-worker` 三 exe),仅用 `SKIP_OBFUSCATE=1` 跳过混淆。
4. **AppId 严格区分**:Inno Setup 的 `AppId` 是安装包唯一标识,两版本必须不同 GUID,否则 Windows 认为同一应用导致升级覆盖。
5. **AI_MODE 通过 `.env.community.example` 声明**:不含 CLOUD_URL,用户自配 `DEEPSEEK_API_KEY` 走离线模式。
6. **不启用 C18 混淆**:混淆是商业保护,Community 版开源 AGPL,不需要混淆(pyarmor 反而违反开源精神)。

---

## 6. `.env.community.example` 处理

**决策**:根目录 `.env.example` **已经是 Community 精简版**(见 Open Core 实现报告 §3.1),内容已满足 Community 用户所有必需配置:

- ✅ `PORT`/`HOST`/`DEBUG`(后端服务)
- ✅ `REDIS_URL`(调度)
- ✅ `PLAYWRIGHT_HEADLESS`、`LAOMA_BROWSER_BACKEND_DEFAULT=patchright`(浏览器)
- ✅ `DEEPSEEK_API_KEY`/`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`OPENAI_MODEL`(自配 LLM key)
- ✅ 注释了 `CLOUD_MAX_ACCOUNTS`/`CLOUD_MAX_PLATFORMS`(Community 默认 3/3,无需修改)
- ✅ `CLOUD_FEATURE_GATE_DISABLED=true`(开发者调试用)
- ❌ 无 `CLOUD_LLM_API_KEY`、无 `CLOUD_LLM_BASE_URL`(那是 Pro 云端 key)
- ❌ `CLOUD_URL`/`CLOUD_ACCESS_TOKEN` 为注释(仅升级 Pro 或对接官方云端时才用)

**处理**:
- **不新建** `.env.community.example` 文件(避免重复维护)
- 在 `package.community.json` 的 `extraResources` 中,把 `../.env.example` **复制**为安装产物中的 `.env.community.example`
- 安装后用户可见:`{安装目录}\resources\.env.community.example`

### 用户配置 Community 版 AI 的最小示例

```ini
# 复制 .env.community.example 为 .env,填入本地 LLM key
PORT=7000
HOST=0.0.0.0
REDIS_URL=redis://localhost:6379/0
PLAYWRIGHT_HEADLESS=true

# 三选一(推荐 DeepSeek,便宜且中文能力强)
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxx
# OPENAI_API_KEY=sk-xxxxxxxxxxxx
# OPENAI_BASE_URL=https://api.deepseek.com/v1
# OPENAI_MODEL=gpt-4o-mini
```

---

## 7. 验证结果

### 7.1 PowerShell 脚本语法

```
SYNTAX OK: desktop-electron\build-community.ps1
  Syntax errors: 0
  Param block parameters: 8
    - BuildNumber (string, default from JSON)
    - SkipFrontend (switch)
    - SkipBackend (switch)
    - SkipPrismenv (switch)
    - OutputRoot (string, default dist-out/community)
    - KeepWinUnpacked (switch)
    - SignInstaller (switch)
    - AutoYes (switch)
  Encoding: UTF-8 with BOM (PowerShell 5.1 兼容)
  Lines: 462
```

### 7.2 JSON 配置校验(node.js)

```
JSON OK:
  name:          laoma-ai-workbench-community
  version:       1.1.0-community
  license:       AGPL-3.0
  build.appId:   com.laomai.workbench.community
  productName:   老马AI工作台 Community
  executableName: LaomaAICommunity
  artifactName:  老马AI工作台-Community-${version}-setup.${ext}
  directories.output: dist-community
  electronVersion: 28.0.0
  extraResources count: 9 (含 .env.community.example 注入)
```

### 7.3 Community vs Pro 差异化校验

| 项 | 独立? |
|---|---|
| `appId` | ✅ `com.laomai.workbench.community` ≠ `com.laomai.workbench` |
| `executableName` | ✅ `LaomaAICommunity` ≠ `LaomaAI` |
| `directories.output` | ✅ `dist-community` ≠ `dist-build` |
| `version` | ✅ `1.1.0-community` ≠ `1.1.0` |
| Inno Setup AppId GUID | ✅ `{3A7C9D2E-...}` ≠ `{8B5F4B5E-...}` |
| Hermes 目录打包 | ✅ Community 无 `tools/hermes-agent`、`tools/hermes-webui` |

### 7.4 未执行完整打包

按任务要求**未执行完整 551MB 打包**(耗时过长)。以下命令在真实环境中应产出:

- `desktop-electron/dist-community/win-unpacked/LaomaAICommunity.exe`
- `desktop-electron/dist-community/老马AI工作台-Community-1.1.0-community-setup.exe`
- `desktop-electron/dist-out/community/v1/老马AI工作台-Community-1.1.0-community-setup.exe`

---

## 8. 用户执行打包的命令

### 8.1 完整打包(推荐首次运行)

```powershell
cd D:\dim开发\Prism-Fusion\desktop-electron
.\build-community.ps1
```

产出:`desktop-electron\dist-out\community\v1\老马AI工作台-Community-1.1.0-community-setup.exe`

### 8.2 加速重打包(前端和 Python 依赖已就绪)

```powershell
.\build-community.ps1 -SkipFrontend -SkipPrismenv
```

只重跑后端 PyInstaller + electron-builder,约 5-10 分钟。

### 8.3 极快打包(仅重打包 electron,前后端产物均已就绪)

```powershell
.\build-community.ps1 -SkipFrontend -SkipBackend -SkipPrismenv -BuildNumber 2
```

只跑 electron-builder + Inno Setup,约 2-3 分钟。

### 8.4 CI 自动化打包

```powershell
.\build-community.ps1 -AutoYes -SkipFrontend -BuildNumber 3
```

`-AutoYes` 关闭末尾 `Read-Host`,便于 CI 无人值守。

### 8.5 产物校验(打包后)

```powershell
$version = "1.1.0-community"
$dir = "D:\dim开发\Prism-Fusion\desktop-electron\dist-out\community\v1"
node scripts\verify-release-assets.mjs $dir $version
node scripts\finalize-windows-release.mjs $dir $version
```

生成 `.blockmap` 和 `latest.yml` 供 electron-updater 差分更新。

### 8.6 与 Pro 版并行打包

Community 与 Pro 版产物、目录、AppId 完全独立,可安全并行运行:

```powershell
# Pro 版打包(独立进程)
cmd /c "scripts\packaging\build-package.bat"

# Community 版打包(独立进程,可并行)
powershell -File "desktop-electron\build-community.ps1"
```

两版本可以**共存安装**在同一 Windows 机器上(AppId 不同)。

---

## 9. 遗留问题

1. **首次打包耗时预估 30-45 分钟**:与 Pro 版相当(prismenv 依赖安装 + PyInstaller 三 target + Next.js 构建 + electron-builder + Inno Setup)。可通过 `-SkipFrontend -SkipPrismenv` 加速重打包至 5-10 分钟。

2. **CLOUD_FEATURE_GATE_DISABLED 默认值**:任务要求默认 `false`(启用 Community 限制)。当前 Open Core 实现的 `feature_gate.py` 中此变量默认即 `false`,**.env.example 里也是默认注释**(不设置即 `false`)。✅ 已符合任务要求。

3. **`MAX_ACCOUNTS` / `MAX_PLATFORMS` 环境变量未定义**:任务描述使用 `MAX_ACCOUNTS=3`,但代码实际使用的是 `CLOUD_MAX_ACCOUNTS` / `CLOUD_MAX_PLATFORMS`(见 Open Core 实现报告 §2.7)。已在 `.env.example` 中以注释形式提示,Community 默认值由 `feature_gate.py` 的 `COMMUNITY_FLAGS` 硬编码提供,无需用户在 .env 中配置。

4. **`AI_MODE=local_key` 未作为 env 变量写入 .env.example**:代码层通过 `CLOUD_AI_MODE`(见 feature_gate.py)控制,默认 Community 即 `local_key`。当前 `.env.example` 通过列出 `DEEPSEEK_API_KEY`/`OPENAI_API_KEY` 等具体 provider key,间接引导用户走本地模式。**是否需要显式 `AI_MODE=local_key` 一行**?当前无对应代码消费此变量,添加会导致"死配置",暂不加。

5. **`verify-release-assets.mjs` 版本正则**:`/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/` 匹配 `1.1.0-community`,✅ 已通过测试(Community 版本号格式与 Pro 版一致,仅多了 `-community` 后缀)。

6. **`finalize-windows-release.mjs` 版本正则**同上,已通过。

7. **未做端到端打包验证**:任务明确"不执行完整打包(551MB 耗时太长)",本报告仅验证脚本语法与配置正确性。建议首次实际打包时在**独立干净环境**跑一次完整流程,验证:
   - `.env.community.example` 是否正确复制到 `resources/` 下
   - Hermes 目录确实未被打包(通过 7zip 解包 exe 验证)
   - Community exe 启动后 AI 调用走本地 key(而非云端代理)
   - Inno Setup 卸载时不删除 Pro 版数据(AppId 隔离)

8. **未接入签名流程**:`-SignInstaller` 参数已预留,但脚本中未实现真正的签名步骤。生产发布时需:
   - 在 `package.community.json` 的 `build.win.certificateFile` 和 `certificatePassword` 中配置代码签名证书
   - electron-builder 会自动在打包时签名
   - 或打包后手动用 `signtool sign` 签名

9. **electron-updater 云端仓库分离**:当前 `build.publish.owner/repo` 均指向 `Laihiujin/laoma-ai-workbench`,与 Pro 版共用。若两个版本共用同一 GitHub Release,`latest.yml` 会互相覆盖。**建议后续**:
   - Pro 版:`github` 仓库 `Laihiujin/laoma-ai-workbench`(pro tag)
   - Community 版:`github` 仓库 `Laihiujin/laoma-ai-workbench-community`(或同一仓库 different channel)
   - 或在 `build.publish.channel` 中区分 `latest` / `community`

10. **`SkipPrismenv` 标记文件命名冲突**:`.community-ready` 与 Pro 版 `.hermes-runtime-ready` 共存于同一 `prismenv/`,不冲突,但语义分散。若日后 Pro 版也需独立打包脚本,建议统一为 `.packaging-ready-{edition}`。

---

## 10. 相关文件一览

**新增**:
- [package.community.json](../../desktop-electron/package.community.json) — Community 版 electron-builder 配置
- [installer-community.iss](../../desktop-electron/installer-community.iss) — Community 版 Inno Setup 脚本
- [build-community.ps1](../../desktop-electron/build-community.ps1) — Community 版完整打包脚本
- [build-version-community.json](../../scripts/packaging/build-version-community.json) — Community 独立版本号
- 本报告

**未改动(Pro 版原样保留)**:
- `desktop-electron/package.json`
- `desktop-electron/installer.iss`
- `scripts/packaging/build-package.bat`
- `scripts/packaging/build-services.ps1`
- `scripts/packaging/build-version.json`
- `.env.example`(已经是 Community 精简版,无需再改)
