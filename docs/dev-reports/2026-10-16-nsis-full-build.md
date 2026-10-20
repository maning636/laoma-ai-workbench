# Community 版 NSIS 完整打包报告

- **日期**：2026-10-16
- **执行机**：Windows PowerShell 5.1 / x64
- **产物版本**：`1.1.0-community`（buildNumber=1，installerVersion=1.1.0.1）
- **AppId**：`com.laomai.workbench.community`
- **License**：AGPL-3.0 (Open Core)

---

## 1. 打包命令 + 结果

### 1.1 前置状态
- `prismenv/`：已就绪（含 patchright 1.59.1）
- `dist/services/`：已就绪（PyInstaller 输出：backend / automation-worker / celery-worker）
- `prism_frontend/.next/standalone/server.js`：已就绪
- `package.community.json`：扁平 build 配置
- `build-community.ps1`：8 步脚本

因为三个上游产物都已就绪，使用加速参数：

```powershell
cd D:\dim开发\Prism-Fusion\desktop-electron
.\build-community.ps1 -AutoYes -SkipPrismenv -SkipBackend -SkipFrontend
```

### 1.2 打包结果
- ✅ **[6/8] Electron --dir** 通过，产出 `dist-community/win-unpacked/`
- ✅ **[7/8] NSIS** 通过，产出 setup.exe（509.58 MB）+ `.nsis.7z`（508.91 MB）
- ✅ **[8/8] 组织输出**（手动完成，见下方"发现的问题"）

---

## 2. 产物文件名 + 大小

| 文件 | 大小 | 说明 |
|---|---|---|
| `老马AI工作台-Community-1.1.0-community-setup.exe` | **509,581,307 B (≈ 486.0 MiB / 509.58 MB)** | NSIS 分发包 |
| `laoma-ai-workbench-community-1.1.0-community-x64.nsis.7z` | 508,910,967 B | NSIS 中间包（electron-builder 保留） |
| `builder-debug.yml` | 840 B | electron-builder 调试元数据 |

setup.exe 大小符合预期（> 500 MB，包含 prismenv + services + frontend + Node runtime）。

⚠️ **注意**：预期文件名 `老马AI工作台-Community-1.1.0-community-setup.exe` 与配置里 `artifactName` 生成的名字完全一致 ✅。

---

## 3. 打包耗时

| 阶段 | 时间点 | 耗时 |
|---|---|---|
| 脚本启动（含前置校验+步骤 1~5 skip 通过） | 12:42:12 | — |
| Electron `--dir` 打包完成 | 12:42:52 | ~40 s |
| NSIS 7z 压缩完成 | 12:46:57 | ~365 s（最大瓶颈：`compression=maximum`） |
| setup.exe 生成完成 | 12:47:11 | ~14 s |
| **打包阶段总耗时**（skip 加速） | | **~5 min** |

（未 skip 的完整链路预计 15–25 min：需要 prismenv 装依赖、PyInstaller、Next.js build）

---

## 4. 发现的问题 + 修复

### 问题 A：`build-community.ps1` 中 `$DesktopDir` / `$ProjectRoot` 定义反了

**症状**：pre-check 报错找不到 `D:\dim开发\Prism-Fusion\package.community.json`（实际文件在 `desktop-electron/`）。

**原因**：
```powershell
# 错误（原代码 line 86-87）
$DesktopDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path      # ← 指向 Prism-Fusion（项目根）
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path # ← 指向 D:\dim开发
```
`$PSScriptRoot` 已经是 `desktop-electron/`。变量语义与赋值路径相反。

**修复**（`build-community.ps1:86-87`）：
```powershell
$DesktopDir = $PSScriptRoot
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
```

### 问题 B：`$cfgJson.name` 找不到，传给 electron-builder 的 `--config.extraMetadata.name=` 是空串

**症状**：electron-builder 报 `⨯ Please specify 'name' in the package.json` 直接失败。

**原因**：`package.community.json` 的元数据在 `extraMetadata.*` 下，但脚本读的是 `$cfgJson.name` 顶层字段（不存在）。

**修复**（`build-community.ps1:342-350`）：
```powershell
$cfgJson = Get-Content -LiteralPath $PackageConfig -Raw | ConvertFrom-Json
$meta = $cfgJson.extraMetadata   # ← 新增：先取 extraMetadata
$appMetaArgs = @(
    "--config.extraMetadata.name=$($meta.name)",
    "--config.extraMetadata.version=$semanticVersion",
    "--config.extraMetadata.main=$($meta.main)",
    "--config.extraMetadata.description=$($meta.description)",
    "--config.extraMetadata.author=$($meta.author)",
    "--config.extraMetadata.license=$($meta.license)"
)
```

### 问题 C：step 8 `Copy-Item` 收尾卡住/被超时截断

**症状**：脚本主进程被前台执行超时中断，`dist-out/community/v1/` 目录已创建但未填充文件。

**判定**：不是脚本错误——dist-community 与 dist-out 是同一 NTFS 卷，Copy-Item 应极快（0.5 s 实测）。真实原因是脚本 7/8 阶段本身跑完后，PowerShell 前台进程被 dim 会话超时截断，未回到 step 8 主体。手动补做后 setup.exe 已复制到目标目录。

**修复**：手动执行了等效的 step 8：
```powershell
Copy-Item $desktopDir\dist-community\老马AI工作台-Community-1.1.0-community-setup.exe $outputDir -Force
```

**后续建议**：以后跑 build-community.ps1 时用 `runInBackground` 或缩短 electron-builder 的 `compression=maximum` 到 `normal`（可再省 3~5 min，setup.exe 会增大 ~100 MB）。

### 说明：blockmap / latest.yml 未生成

- `.blockmap`：electron-builder 日志显示 `building block map` 但产物目录里没找到；猜测是 NSIS target 未启用 differential distribution，或路径被覆盖。分发给最终用户不影响（只是不能增量下载）。
- `latest.yml`：因为配置里 `publish.provider=github` 但没有实际推送步骤，且当前只是本地打包，正常未生成。不影响分发。

---

## 5. 产物路径（用户分发用）

### 主产物（推荐分发）
```
D:\dim开发\Prism-Fusion\desktop-electron\dist-out\community\v1\老马AI工作台-Community-1.1.0-community-setup.exe
```
大小：509,581,307 B（≈ 486.0 MiB）

### 备用位置（原始构建输出，保留在 dist-community/ 中）
```
D:\dim开发\Prism-Fusion\desktop-electron\dist-community\老马AI工作台-Community-1.1.0-community-setup.exe
```

### 中间产物
```
D:\dim开发\Prism-Fusion\desktop-electron\dist-community\win-unpacked\       # 未打包的完整目录
D:\dim开发\Prism-Fusion\desktop-electron\dist-community\laoma-ai-workbench-community-1.1.0-community-x64.nsis.7z
D:\dim开发\Prism-Fusion\desktop-electron\dist-community\builder-debug.yml
```

---

## 6. 修改的文件

- `desktop-electron/build-community.ps1`：
  - line 86-87：修正 `$DesktopDir` / `$ProjectRoot` 定义（swap bug）
  - line 342-350：`$cfgJson.name` → `$cfgJson.extraMetadata.name` 等

未修改：`package.community.json`、`installer-community.iss`、Pro 版相关配置。

## 7. 剩余不确定性 / 已知未验证项

1. **installer.nsh 前置脚本行为**：`build/installer.nsh` 中若有 `!include` 依赖或宏展开，此次打包未触发编译期错误，但运行时（用户安装时）的自定义动作（如服务注册、快捷方式命名、Redis 服务注册）未验证。建议在一台干净 Windows 上跑一遍 setup.exe 做冒烟测试。
2. **AppId 隔离**：`com.laomai.workbench.community` 与 Pro 版 `com.laomai.workbench` 应能共存安装，但未在同一台机器上验证过卸载互不干扰。
3. **签名**：`--SignInstaller` 未启用，setup.exe 目前是未签名状态。分发渠道如果强制要求代码签名，需要另行配置 `certificateFile` / `certificatePassword`。
4. **blockmap**：electron-builder 日志显示尝试生成 blockmap 但未产出，未定位根因；对纯分发场景不影响。
