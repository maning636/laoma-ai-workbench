const { app, BrowserWindow, ipcMain, Menu, Tray, dialog, safeStorage } = require('electron');
const path = require('path');

// 开发模式(!app.isPackaged):把 userData / sessionData 重定向到项目内,
// 避免往 C:\Users\...\AppData\Roaming\laoma-ai-workbench 写数据。
// 必须在 app.whenReady() 之前调用 app.setPath 才生效。
// 打包模式(isPackaged === true)不进入此分支,安装机仍用默认 %APPDATA%。
// 必须放在 app.requestSingleInstanceLock() 与 electron-log 文件路径配置之前,
// 否则单实例锁文件与首条日志仍可能落到旧的 C 盘 userData。
if (!app.isPackaged) {
  // 基于 __dirname 推导项目根:本文件位于 desktop-electron/src/main/,
  // 上溯 3 层即仓库根目录,保证任意机器从源码运行都落到本项目内,
  // 不硬编码开发者本机绝对路径(旧版曾写死 D:\dim开发\Prism-Fusion)。
  const devUserDataRoot = path.resolve(__dirname, '..', '..', '..', '_electron_userdata');
  // userData: 控制 config / data / hermes / logs 等
  app.setPath('userData', devUserDataRoot);
  // sessionData: 控制 Cache / Code Cache / GPUCache / Local Storage 等
  app.setPath('sessionData', devUserDataRoot);
}

const { nativeTheme } = require('electron');
const { spawn, spawnSync, execSync } = require('child_process');
const net = require('net');
const log = require('electron-log');
const fs = require('fs');
const {
  registerUpdateHandlers,
  startUpdateManager,
  stopUpdateManager,
  checkForUpdates
} = require('./update-manager');
const { getVersionInfo: buildVersionInfo, aboutDetail } = require('./version-info');

/**
 * 读 JSON 文件，顺手剥掉可能存在的 BOM。
 *
 * Windows 上用 PowerShell 的 `Set-Content -Encoding UTF8` 改过的 JSON，
 * 文件开头会多一个 U+FEFF。`JSON.parse` 不接受它（U+FEFF 不是合法 JSON 空白），
 * 会直接抛 SyntaxError —— 于是一个 BOM 就能让整段配置读取静默走进 catch 分支，
 * 读出来的是空值而不是"文件坏了"的显式报错。
 *
 * 这个坑踩过一次：`desktop-electron/package.json` 被 PowerShell 改版本号时
 * 写进了 BOM，而 `getCloudBaseUrl()` 用 JSON.parse 读它 —— 结果 laomaCloudUrl
 * 读不到，云端地址退回占位域名，整条商业闭环（注册码同步 / 云端订阅 / 云端生图）
 * 静默失效。这里统一收口。
 */
function readJsonFileSafely(filePath) {
  const raw = fs.readFileSync(filePath, 'utf-8');
  return JSON.parse(raw.replace(/^\uFEFF/, ''));
}

// 配置日志
log.transports.file.level = 'info';
log.transports.console.level = 'debug';

    // 单实例锁 — 防止多次启动
const gotTheLock = app.requestSingleInstanceLock();

if (!gotTheLock) {
  console.log('另一个老马AI工作台实例已在运行，退出。');
  log.info('另一个老马AI工作台实例已在运行，退出。');
  app.quit();
  process.exit(0);
}

// 娣诲姞鎺у埗鍙拌緭鍑轰互渚胯皟璇?
console.log('=== Electron Main Process Starting ===');
console.log('Log file path:', log.transports.file.getFile().path);

class PrismApp {
  constructor() {
    this.mainWindow = null;
    this.launcherWindow = null;
    this.settingsWindow = null;
    this.backendProcess = null;
    this.celeryProcess = null;
    this.redisProcess = null;
    this.automationWorkerProcess = null;
    this.frontendProcess = null;
    this.supervisorProcess = null;
    this.automationBrowserPath = null;
    this.visualBrowserWindows = new Map();
    this.servicesStarted = false;
    this.appIconPath = null;
    this.tray = null;
    this.isQuitting = false;
    this.isRestarting = false;
    this.isPackagedRuntime = false;
    this.frontendPort = 3000;
    this.backendPort = null;
    this.automationWorkerPort = null;
    // 动态 supervisor API 端口（supervisor 启动后经状态文件发现）
    this.supervisorApiPort = null;
    this.supervisorStatePath = null;
    this.supervisorLaunchToken = null;
    this.runtimeSettings = {
      browserHeadless: true,
      automationRuntime: 'patchright'
    };
  }

  useExternalStack() {
    return process.env.LAOMA_USE_EXTERNAL_STACK === '1';
  }

  async initialize() {
    console.log('老马AI工作台正在启动...');
    log.info('老马AI工作台正在启动...');

    // 等待 Electron 准备就绪
    await app.whenReady();
    nativeTheme.themeSource = 'dark';
    log.info('Applied default dark theme source for Electron browser surfaces');

    this.repoRoot = path.join(__dirname, '../../../');
    this.isPackagedRuntime = this.detectPackagedRuntime();
    this.isDev = !this.isPackagedRuntime;
    const supervisorPaths = this.getSupervisorPaths();
    const supervisorExists = Boolean(supervisorPaths.exePath || supervisorPaths.scriptPath);
    this.appIconPath = this.getAppIconPath();
    this.runtimeSettings = this.loadRuntimeSettings();
    process.env.PLAYWRIGHT_HEADLESS = this.runtimeSettings.browserHeadless ? 'true' : 'false';
    process.env.LAOMA_AUTOMATION_RUNTIME = this.runtimeSettings.automationRuntime;
    this.applyPlatformBrowserPreferenceEnv(process.env, this.runtimeSettings.platformBrowserPreferences || {});
    this.applyPlatformProxyPreferenceEnv(process.env, this.runtimeSettings.platformProxyPreferences || {});
    this.setupTray();

    console.log('App ready. isDev:', this.isDev, 'isPackaged:', app.isPackaged, 'isPackagedRuntime:', this.isPackagedRuntime);
    console.log('resourcesPath:', process.resourcesPath);
    console.log('supervisor paths:', supervisorPaths);
    log.info('App ready. isDev:', this.isDev, 'isPackaged:', app.isPackaged, 'isPackagedRuntime:', this.isPackagedRuntime);
    log.info('resourcesPath:', process.resourcesPath);
    log.info('supervisor paths:', supervisorPaths);

    // 1. 设置 Playwright 浏览器路径
    this.setupAutomationPath();

    // 2. 启动后端/前端服务（生产默认启动，开发可用 LAOMA_START_SERVICES=1 强制开）
    const useExternalStack = this.useExternalStack();
    const shouldStartServices = !useExternalStack && (process.env.LAOMA_START_SERVICES === '1' || !this.isDev);
    const showLauncher = process.env.LAOMA_SHOW_LAUNCHER === '1'; // 是否显示启动管理器
    console.log('Use external stack:', useExternalStack);
    console.log('Should start services:', shouldStartServices, '(isDev:', this.isDev, ')');
    console.log('Show launcher:', showLauncher);
    log.info('Use external stack:', useExternalStack);
    log.info('Should start services:', shouldStartServices, '(isDev:', this.isDev, ')');
    log.info('Show launcher:', showLauncher);

    if (shouldStartServices) {
      console.log('Starting services...');
      log.info('Starting services...');
      try {
        await this.startServices();
      } catch (error) {
        // 失败根因上报：弹窗展示诊断摘要 + 写入日志
        const message = error instanceof Error ? error.message : String(error);
        log.error('Services failed to start:', error);
        const diagnostics = await this.getSupervisorDiagnostics(5000);
        const detail = this.summarizeDiagnostics(diagnostics);
        dialog.showMessageBoxSync({
          type: 'error',
          title: '老马AI工作台服务启动失败',
          message: message.slice(0, 400),
          detail: detail || `诊断详情见日志: ${log.transports.file.getFile().path}`,
          buttons: ['确定']
        });
      }
      console.log('Services started');
      log.info('Services started');
    }

    // 3. 创建窗口（如果启用启动管理器，则显示启动管理器；否则创建主窗口）
    if (showLauncher) {
      this.createLauncherWindow();
    } else {
      this.createMainWindow();
    }

    // 4. 设置 IPC 处理
    this.setupIPC();

    // 5. 设置应用事件
    this.setupAppEvents();

    // 6. 应用菜单（帮助：检查更新 / 关于-双版本体系）
    this.setupAppMenu();

    // 7. 更新管理器（自托管更新通道，参考 dsh-desktop）
    registerUpdateHandlers();
    startUpdateManager({
      prepareToInstall: async () => {
        try {
          await this.stopManagedServices();
        } catch (error) {
          log.warn('prepareToInstall: failed to stop managed services:', error);
        }
      }
    });

    log.info('老马AI工作台 startup complete');
  }

  setupAppMenu() {
    const template = [
      {
        label: '帮助',
        submenu: [
          {
            label: '检查更新…',
            click: () => {
              void checkForUpdates(true).then((updateStatus) => {
                if (!updateStatus) return;
                const phase = updateStatus.phase;
                let title = '检查更新';
                let message = '正在检查更新…';
                if (phase === 'up-to-date') {
                  message = `当前已是最新版本（${updateStatus.currentVersion}）。`;
                } else if (phase === 'available') {
                  message = `发现新版本：${updateStatus.availableVersion}。请到启动管理器下载安装。`;
                } else if (phase === 'error') {
                  title = '检查更新失败';
                  message = updateStatus.message || '更新检查出错，请稍后重试。';
                } else if (phase === 'unsupported') {
                  title = '检查更新';
                  message = updateStatus.message || '仅安装版支持自动更新。';
                }
                dialog.showMessageBox({ type: 'info', title, message });
              });
            }
          },
          { type: 'separator' },
          {
            label: '关于 老马AI工作台',
            click: () => {
              dialog.showMessageBox({
                type: 'info',
                title: '关于 老马AI工作台',
                message: '老马AI工作台',
                detail: aboutDetail(this.getVersionInfo(), 'zh')
              });
            }
          }
        ]
      }
    ];
    Menu.setApplicationMenu(Menu.buildFromTemplate(template));
  }

  setupAutomationPath() {
    // 获取打包后的资源路径
    const isDev = this.isDev;

    if (isDev) {
      // 开发环境：使用项目根目录的浏览器
      this.automationBrowserPath = path.join(__dirname, '../../../browsers');
      log.info('Dev mode Playwright browser path:', this.automationBrowserPath);
    } else {
      // 生产环境：使用打包后的浏览器
      this.automationBrowserPath = path.join(process.resourcesPath, 'browsers');
      log.info('Packaged mode Playwright browser path:', this.automationBrowserPath);
    }

    // 设置环境变量，让 Playwright 使用指定的浏览器
    process.env.PLAYWRIGHT_BROWSERS_PATH = this.automationBrowserPath;

    // 验证浏览器是否存在
    if (fs.existsSync(this.automationBrowserPath)) {
      log.info('Playwright browser path is ready');
    } else {
      log.warn('Playwright browser path does not exist; automation features may be unavailable.');
    }
  }

  detectPackagedRuntime() {
    if (app.isPackaged) {
      return true;
    }

    const executableName = path.basename(process.execPath || '').toLowerCase();
    const runningViaElectronBinary = executableName === 'electron.exe' || executableName === 'electron';
    const packagedMarkers = [
      path.join(process.resourcesPath, 'supervisor', 'supervisor.exe'),
      path.join(process.resourcesPath, 'frontend', 'standalone', 'server.js'),
      path.join(process.resourcesPath, 'services', 'backend', 'backend.exe')
    ];

    return !runningViaElectronBinary && packagedMarkers.some((markerPath) => fs.existsSync(markerPath));
  }

  getResourcesRoot() {
    return this.isDev ? this.repoRoot : process.resourcesPath;
  }

  getSupervisorPaths() {
    const packagedExePath = path.join(process.resourcesPath, 'supervisor', 'supervisor.exe');
    const packagedScriptPath = path.join(process.resourcesPath, 'supervisor', 'supervisor.py');
    const devSupervisorDir = path.join(this.repoRoot, 'desktop-electron', 'resources', 'supervisor');
    const devExePath = path.join(devSupervisorDir, 'supervisor.exe');
    const devScriptPath = path.join(devSupervisorDir, 'supervisor.py');
    const preferScriptInDev = this.isDev;
    const exePath = preferScriptInDev
      ? null
      : this.resolveFirstPath([packagedExePath, devExePath]);
    const scriptPath = this.resolveFirstPath(
      preferScriptInDev
        ? [devScriptPath, packagedScriptPath]
        : exePath
          ? []
          : [packagedScriptPath, devScriptPath]
    );
    const fallbackExePath = exePath || (
      scriptPath
        ? null
        : this.resolveFirstPath(
            this.isDev
              ? [devExePath, packagedExePath]
              : [packagedExePath, devExePath]
          )
    );

    return {
      exePath: fallbackExePath,
      scriptPath,
      cwd: fallbackExePath ? path.dirname(fallbackExePath) : (scriptPath ? path.dirname(scriptPath) : null)
    };
  }

  normalizeBackendUrl(rawUrl) {
    const fallbackPort = this.resolveBackendPort(rawUrl);
    const fallback = `http://127.0.0.1:${fallbackPort}`;
    const candidate = String(rawUrl || '').trim().replace(/\/+$/, '') || fallback;

    try {
      const url = new URL(candidate);
      if (url.hostname === 'localhost') {
        url.hostname = '127.0.0.1';
      }
      return url.toString().replace(/\/+$/, '');
    } catch (error) {
      return fallback;
    }
  }

  getConfiguredBackendPort(rawUrl) {
    const envPort = [
      process.env.LAOMA_BACKEND_PORT,
      process.env.BACKEND_PORT
    ].find((value) => String(value || '').trim());

    const parsedEnvPort = Number.parseInt(envPort, 10);
    if (Number.isInteger(parsedEnvPort) && parsedEnvPort > 0) {
      return parsedEnvPort;
    }

    try {
      if (rawUrl) {
        const url = new URL(String(rawUrl).trim());
        const parsedUrlPort = Number.parseInt(url.port, 10);
        if (Number.isInteger(parsedUrlPort) && parsedUrlPort > 0) {
          return parsedUrlPort;
        }
      }
    } catch (error) {
      // Ignore malformed URL and fall back to the default port.
    }

    return 7000;
  }

  resolveBackendPort(rawUrl) {
    const configuredPort = this.getConfiguredBackendPort(rawUrl);
    const selectedPort = Number.parseInt(String(this.backendPort || ''), 10);
    if (Number.isInteger(selectedPort) && selectedPort > 0) {
      return selectedPort;
    }
    return configuredPort;
  }

  getBackendBaseUrl() {
    const rawUrl = [
      process.env.LAOMA_BACKEND_URL,
      process.env.NEXT_PUBLIC_LAOMA_BACKEND_URL,
      process.env.NEXT_PUBLIC_BACKEND_URL
    ].find((value) => String(value || '').trim());

    return this.normalizeBackendUrl(rawUrl);
  }

  getBackendPort() {
    return this.resolveBackendPort(this.getBackendBaseUrl());
  }

  getConfiguredAutomationWorkerPort() {
    const envPort = [
      process.env.AUTOMATION_WORKER_PORT,
      process.env.LAOMA_AUTOMATION_WORKER_PORT
    ].find((value) => String(value || '').trim());

    const parsedEnvPort = Number.parseInt(envPort, 10);
    if (Number.isInteger(parsedEnvPort) && parsedEnvPort > 0) {
      return parsedEnvPort;
    }

    return 7001;
  }

  getAutomationWorkerPort() {
    const selectedPort = Number.parseInt(String(this.automationWorkerPort || ''), 10);
    if (Number.isInteger(selectedPort) && selectedPort > 0) {
      return selectedPort;
    }
    return this.getConfiguredAutomationWorkerPort();
  }

  getBackendApiBaseUrl() {
    return `${this.getBackendBaseUrl()}/api/v1`;
  }

  getSystemApiBaseUrl() {
    return `${this.getBackendApiBaseUrl()}/system`;
  }

  getPreferredFrontendPort() {
    const envPort = [
      process.env.PRISM_FRONTEND_PORT,
      process.env.FRONTEND_PORT,
      process.env.PORT
    ].find((value) => String(value || '').trim());

    const parsedEnvPort = Number.parseInt(envPort, 10);
    if (Number.isInteger(parsedEnvPort) && parsedEnvPort > 0) {
      return parsedEnvPort;
    }

    return 3000;
  }

  getFrontendPort() {
    const currentPort = Number.parseInt(String(this.frontendPort || ''), 10);
    if (Number.isInteger(currentPort) && currentPort > 0) {
      return currentPort;
    }
    return this.getPreferredFrontendPort();
  }

  getFrontendBaseUrl() {
    return `http://127.0.0.1:${this.getFrontendPort()}`;
  }

  async findAvailablePort(preferredPort, attempts = 20) {
    for (let offset = 0; offset < attempts; offset += 1) {
      const candidatePort = preferredPort + offset;
      if (await this.canBindPort(candidatePort)) {
        return candidatePort;
      }
    }

    throw new Error(`Unable to find an available port starting from ${preferredPort}`);
  }

  async resolveManagedPort(preferredPort, ownsPortCheck, reservedPorts = new Set(), attempts = 20) {
    for (let offset = 0; offset < attempts; offset += 1) {
      const candidatePort = preferredPort + offset;
      if (reservedPorts.has(candidatePort)) {
        continue;
      }

      if (await this.isPortInUse(candidatePort)) {
        if (ownsPortCheck && await ownsPortCheck(candidatePort)) {
          return candidatePort;
        }
        continue;
      }

      if (await this.canBindPort(candidatePort)) {
        return candidatePort;
      }
    }

    throw new Error(`Unable to resolve managed port starting from ${preferredPort}`);
  }

  getRuntimeSettingsPath() {
    return path.join(app.getPath('userData'), 'runtime-settings.json');
  }

  normalizeBooleanSetting(value, defaultValue = true) {
    if (typeof value === 'boolean') {
      return value;
    }
    if (typeof value === 'string') {
      const normalized = value.trim().toLowerCase();
      if (['true', '1', 'yes', 'on'].includes(normalized)) {
        return true;
      }
      if (['false', '0', 'no', 'off'].includes(normalized)) {
        return false;
      }
    }
    if (typeof value === 'number') {
      if (value === 1) {
        return true;
      }
      if (value === 0) {
        return false;
      }
    }
    return defaultValue;
  }

  getDefaultPlatformBrowserPreferences() {
    return {
      douyin: 'chromium',
      kuaishou: 'chromium',
      xiaohongshu: 'chromium',
      channels: 'chromium',
      bilibili: 'chromium'
    };
  }

  normalizePlatformBrowserKey(value) {
    const normalized = String(value || '').trim().toLowerCase();
    if (normalized === 'tencent') {
      return 'channels';
    }
    return normalized;
  }

  normalizePlatformBrowserChoice(value, fallback = 'chromium') {
    return ['auto', 'chromium', 'firefox'].includes(value) ? value : fallback;
  }

  normalizePlatformBrowserPreferences(raw = {}) {
    const defaults = this.getDefaultPlatformBrowserPreferences();
    const normalized = { ...defaults };

    for (const [platform, defaultChoice] of Object.entries(defaults)) {
      const directValue = raw?.[platform];
      const aliasValue = platform === 'channels' ? raw?.tencent : undefined;
      const candidate = typeof directValue === 'string'
        ? directValue.trim().toLowerCase()
        : typeof aliasValue === 'string'
          ? aliasValue.trim().toLowerCase()
          : null;
      normalized[platform] = this.normalizePlatformBrowserChoice(candidate, defaultChoice);
    }

    return normalized;
  }

  normalizeRuntimeSettings(raw = {}) {
    return {
      browserHeadless: this.normalizeBooleanSetting(raw.browserHeadless, true),
      automationRuntime: 'patchright',
      platformBrowserPreferences: this.normalizePlatformBrowserPreferences(raw.platformBrowserPreferences),
      platformProxyPreferences: this.normalizePlatformProxyPreferences(raw.platformProxyPreferences)
    };
  }

  getDefaultPlatformProxyPreferences() {
    return {
      douyin: 'direct',
      kuaishou: 'direct',
      xiaohongshu: 'direct',
      channels: 'direct',
      bilibili: 'direct'
    };
  }

  normalizePlatformProxyChoice(value, fallback = 'direct') {
    return ['direct', 'inherit'].includes(value) ? value : fallback;
  }

  normalizePlatformProxyPreferences(raw = {}) {
    const defaults = this.getDefaultPlatformProxyPreferences();
    const normalized = { ...defaults };

    for (const [platform, defaultChoice] of Object.entries(defaults)) {
      const directValue = raw?.[platform];
      const aliasValue = platform === 'channels' ? raw?.tencent : undefined;
      const candidate = typeof directValue === 'string'
        ? directValue.trim().toLowerCase()
        : typeof aliasValue === 'string'
          ? aliasValue.trim().toLowerCase()
          : undefined;
      normalized[platform] = this.normalizePlatformProxyChoice(candidate, defaultChoice);
    }

    return normalized;
  }

  // 把平台代理偏好转成后端可消费的 LAOMA_DIRECT_PLATFORMS（逗号分隔的“强制直连”平台列表）。
  // 只有标记为 direct 的平台才会走直连；tiktok/youtube 等未配置平台默认走代理。
  buildDirectConnectPlatforms(rawPreferences = {}) {
    const preferences = this.normalizePlatformProxyPreferences(rawPreferences);
    const direct = [];
    for (const [platform, mode] of Object.entries(preferences)) {
      if (mode === 'direct') {
        direct.push(platform === 'channels' ? 'tencent' : platform);
      }
    }
    return direct;
  }

  applyPlatformProxyPreferenceEnv(targetEnv, rawPreferences = {}) {
    const direct = this.buildDirectConnectPlatforms(rawPreferences);
    targetEnv.LAOMA_DIRECT_PLATFORMS = direct.join(',');
    return targetEnv.LAOMA_DIRECT_PLATFORMS;
  }

  applyPlatformBrowserPreferenceEnv(targetEnv, rawPreferences = {}) {
    const preferences = this.normalizePlatformBrowserPreferences(rawPreferences);
    targetEnv.PRISM_PLATFORM_BROWSER_PREFERENCES = JSON.stringify(preferences);
    for (const [platform, choice] of Object.entries(preferences)) {
      targetEnv[`PRISM_PLATFORM_BROWSER_${platform.toUpperCase()}`] = choice;
    }
    targetEnv.PRISM_PLATFORM_BROWSER_TENCENT = preferences.channels;
    return preferences;
  }

  loadRuntimeSettings() {
    const settingsPath = this.getRuntimeSettingsPath();
    try {
      if (!fs.existsSync(settingsPath)) {
        return this.normalizeRuntimeSettings();
      }
      return this.normalizeRuntimeSettings(readJsonFileSafely(settingsPath));
    } catch (error) {
      log.warn('Failed to load runtime settings; using defaults:', error);
      return this.normalizeRuntimeSettings();
    }
  }

  saveRuntimeSettings(nextSettings = {}) {
    const settings = this.normalizeRuntimeSettings({
      ...this.runtimeSettings,
      ...nextSettings
    });
    const settingsPath = this.getRuntimeSettingsPath();
    fs.mkdirSync(path.dirname(settingsPath), { recursive: true });
    fs.writeFileSync(settingsPath, JSON.stringify(settings, null, 2), 'utf8');
    this.runtimeSettings = settings;
    process.env.PLAYWRIGHT_HEADLESS = settings.browserHeadless ? 'true' : 'false';
    process.env.LAOMA_AUTOMATION_RUNTIME = settings.automationRuntime;
    this.applyPlatformBrowserPreferenceEnv(process.env, settings.platformBrowserPreferences || {});
    this.applyPlatformProxyPreferenceEnv(process.env, settings.platformProxyPreferences || {});
    return settings;
  }

  getBackendDir() {
    return this.isDev
      ? path.join(this.repoRoot, 'prism_backend')
      : path.join(process.resourcesPath, 'prism_backend');
  }

  getPythonPath() {
    return this.getPythonRuntime().path;
  }

  getPrismenvSitePackagesPath() {
    const candidates = [
      path.join(this.getResourcesRoot(), 'prismenv', 'Lib', 'site-packages'),
      path.join(this.getResourcesRoot(), 'prismenv', 'lib', 'site-packages')
    ];
    return this.resolveFirstPath(candidates) || null;
  }

  buildPythonEnv(baseEnv = process.env) {
    const sitePackagesPath = this.getPrismenvSitePackagesPath();
    if (!sitePackagesPath) {
      return baseEnv;
    }

    const existing = String(baseEnv.PYTHONPATH || '')
      .split(path.delimiter)
      .filter((entry) => entry && entry !== sitePackagesPath);
    return {
      ...baseEnv,
      PYTHONPATH: [sitePackagesPath, ...existing].join(path.delimiter)
    };
  }

  testPythonExecutable(command, args = []) {
    try {
      const result = spawnSync(command, [...args, '-c', 'import sys; print(sys.version)'], {
        cwd: this.getResourcesRoot(),
        env: this.buildPythonEnv(process.env),
        encoding: 'utf8',
        windowsHide: true,
        timeout: 10000
      });

      if (result.error) {
        return { ok: false, error: result.error.message };
      }
      if (result.status !== 0) {
        return {
          ok: false,
          error: String(result.stderr || result.stdout || '').trim() || `python_probe_failed:${result.status}`
        };
      }
      return { ok: true, version: String(result.stdout || '').trim() };
    } catch (error) {
      return { ok: false, error: error.message };
    }
  }

  shouldReuseCachedPythonRuntime() {
    if (!this.pythonRuntimeCache) {
      return false;
    }

    if (this.pythonRuntimeCache.source !== 'prismenv') {
      return false;
    }

    return fs.existsSync(this.pythonRuntimeCache.path);
  }

  getPythonRuntime() {
    if (this.shouldReuseCachedPythonRuntime()) {
      return this.pythonRuntimeCache;
    }

    const packagedPython = path.join(this.getResourcesRoot(), 'prismenv', 'Scripts', 'python.exe');
    const candidates = [];
    if (fs.existsSync(packagedPython)) {
      candidates.push({ path: packagedPython, args: [], source: 'prismenv' });
    }
    candidates.push({ path: 'python', args: [], source: 'system' });

    const failures = [];
    for (const candidate of candidates) {
      const probe = this.testPythonExecutable(candidate.path, candidate.args);
      if (probe.ok) {
        this.pythonRuntimeCache = {
          path: candidate.path,
          args: candidate.args,
          source: candidate.source,
          version: probe.version,
          sitePackagesPath: this.getPrismenvSitePackagesPath(),
          error: null
        };
        if (candidate.source !== 'prismenv') {
          log.warn('Packaged prismenv Python is unavailable; using fallback Python:', candidate.path);
        }
        return this.pythonRuntimeCache;
      }
      failures.push(`${candidate.source}:${probe.error}`);
    }

    this.pythonRuntimeCache = {
      path: packagedPython,
      args: [],
      source: 'missing',
      version: null,
      sitePackagesPath: this.getPrismenvSitePackagesPath(),
      error: failures.join(' | ')
    };
    return this.pythonRuntimeCache;
  }

  getNpmCommand() {
    if (process.platform !== 'win32') {
      return 'npm';
    }
    const candidates = [
      process.env.npm_execpath,
      path.join(process.env.ProgramFiles || 'C:\\Program Files', 'nodejs', 'npm.cmd'),
      path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'nodejs', 'npm.cmd')
    ].filter((candidate) => candidate && /\.(cmd|exe)$/i.test(candidate));
    return this.resolveFirstPath(candidates) || 'npm.cmd';
  }

  getNodeCommand() {
    if (process.platform !== 'win32') {
      return 'node';
    }
    return this.resolveFirstPath([
      path.join(process.env.ProgramFiles || 'C:\\Program Files', 'nodejs', 'node.exe'),
      path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'nodejs', 'node.exe')
    ]) || 'node.exe';
  }

  ensurePrismenvConfig() {
    if (this.isDev) {
      return;
    }

    const runtime = this.getPythonRuntime();
    if (runtime.source === 'missing') {
      log.error('No usable Python runtime found:', runtime.error);
    } else {
      log.info('Python runtime selected:', runtime.path, `(${runtime.source})`);
      if (runtime.sitePackagesPath) {
        log.info('Packaged Python site-packages exposed via PYTHONPATH:', runtime.sitePackagesPath);
      }
    }
  }

  getBrowsersRoot() {
    return this.isDev
      ? path.join(this.repoRoot, 'browsers')
      : path.join(process.resourcesPath, 'browsers');
  }

  resolveFirstPath(candidates) {
    return candidates.find((candidate) => candidate && fs.existsSync(candidate));
  }

  getSubdirs(root, prefix) {
    try {
      return fs.readdirSync(root, { withFileTypes: true })
        .filter((entry) => entry.isDirectory() && entry.name.startsWith(prefix))
        .map((entry) => path.join(root, entry.name))
        .sort()
        .reverse();
    } catch (error) {
      return [];
    }
  }

  resolveChromePath(browsersRoot) {
    const chromiumRoot = path.join(browsersRoot, 'chromium');
    const candidates = [];

    for (const dir of this.getSubdirs(chromiumRoot, 'hibbiki-')) {
      candidates.push(path.join(dir, 'Chrome-bin', 'chrome.exe'));
    }
    for (const dir of this.getSubdirs(browsersRoot, 'chromium-')) {
      candidates.push(path.join(dir, 'chrome-win64', 'chrome.exe'));
      candidates.push(path.join(dir, 'chrome-win', 'chrome.exe'));
    }
    for (const dir of this.getSubdirs(chromiumRoot, 'chromium-')) {
      candidates.push(path.join(dir, 'chrome-win64', 'chrome.exe'));
      candidates.push(path.join(dir, 'chrome-win', 'chrome.exe'));
    }
    for (const dir of this.getSubdirs(path.join(browsersRoot, 'chrome-for-testing'), 'chrome-')) {
      candidates.push(path.join(dir, 'chrome-win64', 'chrome.exe'));
    }

    return this.resolveFirstPath(candidates) || null;
  }

  resolveFirefoxPath(browsersRoot) {
    const candidates = [];

    for (const dir of this.getSubdirs(browsersRoot, 'firefox-')) {
      candidates.push(path.join(dir, 'firefox', 'firefox.exe'));
    }
    for (const dir of this.getSubdirs(path.join(browsersRoot, 'firefox'), 'firefox-')) {
      candidates.push(path.join(dir, 'firefox', 'firefox.exe'));
    }

    return this.resolveFirstPath(candidates) || null;
  }

  getBrowserAssetVersion(executablePath) {
    if (!executablePath) {
      return null;
    }

    const parts = String(executablePath).split(/[\\/]+/).reverse();
    const prefixes = ['hibbiki-', 'chromium-', 'chrome-', 'firefox-'];
    return parts.find((part) => prefixes.some((prefix) => part.startsWith(prefix))) || null;
  }

  getPythonPackageInfo(packageName) {
    const runtime = this.getPythonRuntime();
    const pythonPath = runtime.path;
    const inspectCode = [
      'import importlib.metadata',
      'import importlib.util',
      'import pathlib',
      'import json',
      `name = ${JSON.stringify(packageName)}`,
      'payload = {"installed": False, "version": None, "error": None, "driverInstalled": None, "driverPath": None}',
      'spec = importlib.util.find_spec(name)',
      'if spec is not None:',
      '    payload["installed"] = True',
      '    try:',
      '        payload["version"] = importlib.metadata.version(name)',
      '    except Exception:',
      '        payload["version"] = None',
      '    try:',
      '        pkg_dir = pathlib.Path(spec.origin).resolve().parent if spec.origin else None',
      '        driver = pkg_dir / "driver" / ("node.exe" if __import__("sys").platform == "win32" else "node") if pkg_dir else None',
      '        payload["driverPath"] = str(driver) if driver else None',
      '        payload["driverInstalled"] = bool(driver and driver.exists())',
      '    except Exception as exc:',
      '        payload["driverInstalled"] = False',
      '        payload["error"] = str(exc)',
      'print(json.dumps(payload, ensure_ascii=True))'
    ].join('\n');

    try {
      if (runtime.source === 'missing') {
        return {
          installed: false,
          version: null,
          driverInstalled: false,
          driverPath: null,
          error: runtime.error || 'python_runtime_unavailable'
        };
      }

      const result = spawnSync(pythonPath, [...runtime.args, '-c', inspectCode], {
        cwd: this.getResourcesRoot(),
        env: this.buildPythonEnv(process.env),
        encoding: 'utf8',
        windowsHide: true
      });

      if (result.error) {
        return {
          installed: false,
          version: null,
          driverInstalled: false,
          driverPath: null,
          error: result.error.message
        };
      }

      const raw = String(result.stdout || '').trim();
      if (!raw) {
        return {
          installed: false,
          version: null,
          driverInstalled: false,
          driverPath: null,
          error: String(result.stderr || '').trim() || 'empty_python_package_probe'
        };
      }

      return JSON.parse(raw);
    } catch (error) {
      return {
        installed: false,
        version: null,
        driverInstalled: false,
        driverPath: null,
        error: error.message
      };
    }
  }

  getPackagedWorkerRuntimeInfo(packageName) {
    const packageRoot = path.join(
      this.getResourcesRoot(),
      'services',
      'automation-worker',
      '_internal',
      packageName
    );
    if (!fs.existsSync(packageRoot)) {
      return {
        installed: false,
        version: null,
        driverInstalled: false,
        driverPath: null,
        error: null
      };
    }

    const driverPath = path.join(
      packageRoot,
      'driver',
      process.platform === 'win32' ? 'node.exe' : 'node'
    );
    return {
      installed: true,
      version: null,
      driverInstalled: fs.existsSync(driverPath),
      driverPath,
      source: 'packaged-worker',
      error: fs.existsSync(driverPath) ? null : 'driver_missing'
    };
  }

  mergeRuntimeInfo(pythonInfo, packagedInfo) {
    if (pythonInfo.installed) {
      return {
        ...pythonInfo,
        source: pythonInfo.source || 'python',
        driverInstalled: pythonInfo.driverInstalled || packagedInfo.driverInstalled,
        driverPath: pythonInfo.driverInstalled ? pythonInfo.driverPath : packagedInfo.driverPath
      };
    }
    if (packagedInfo.installed) {
      return packagedInfo;
    }
    return pythonInfo;
  }

  getBrowserRuntimeInfo() {
    const browsersRoot = this.getBrowsersRoot();
    const chromiumPath = this.resolveChromePath(browsersRoot);
    const firefoxPath = this.resolveFirefoxPath(browsersRoot);
    const patchrightInfo = this.mergeRuntimeInfo(
      this.getPythonPackageInfo('patchright'),
      this.getPackagedWorkerRuntimeInfo('patchright')
    );
    const preferredRuntime = 'patchright';

    let activeRuntime = null;
    const patchrightReady = patchrightInfo.installed && patchrightInfo.driverInstalled !== false;
    if (patchrightReady) {
      activeRuntime = 'patchright';
    }

    return {
      pythonPath: this.getPythonPath(),
      pythonRuntime: this.getPythonRuntime(),
      browsersPath: browsersRoot,
      preferredRuntime,
      activeRuntime,
      platformBrowserPreferences: this.runtimeSettings.platformBrowserPreferences,
      runtimes: {
        patchright: patchrightInfo
      },
      browsers: {
        chromium: {
          installed: Boolean(chromiumPath),
          path: chromiumPath,
          version: this.getBrowserAssetVersion(chromiumPath),
          uninstallable: true
        },
        firefox: {
          installed: Boolean(firefoxPath),
          path: firefoxPath,
          version: this.getBrowserAssetVersion(firefoxPath),
          uninstallable: true,
          required: false
        }
      }
    };
  }

  getHibbikiInstallerPath() {
    return this.resolveFirstPath([
      path.join(this.getResourcesRoot(), 'scripts', 'packaging', 'install_hibbiki_chromium.ps1'),
      path.join(this.repoRoot, 'scripts', 'packaging', 'install_hibbiki_chromium.ps1')
    ]);
  }

  async installHibbikiChromium() {
    const scriptPath = this.getHibbikiInstallerPath();
    if (!scriptPath) {
      return {
        success: false,
        output: '',
        error: 'hibbiki_installer_not_found'
      };
    }

    const env = this.buildPythonEnv({
      ...process.env,
      PLAYWRIGHT_BROWSERS_PATH: this.getBrowsersRoot(),
      LAOMA_AUTOMATION_RUNTIME: this.runtimeSettings.automationRuntime
    });

    return this.runManagedCommand(
      'powershell.exe',
      [
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', scriptPath,
        '-ProjectRoot', this.getResourcesRoot(),
        '-Clean'
      ],
      { env, logPrefix: 'hibbiki:chromium' }
    );
  }

  getBrowserAssetRemovalTargets(target) {
    const browsersRoot = this.getBrowsersRoot();

    if (target === 'chromium') {
      return [
        path.join(browsersRoot, 'chromium'),
        ...this.getSubdirs(browsersRoot, 'chromium-'),
        ...this.getSubdirs(browsersRoot, 'chromium_headless_shell-'),
        path.join(browsersRoot, 'chrome-for-testing')
      ];
    }

    if (target === 'firefox') {
      return [
        path.join(browsersRoot, 'firefox'),
        ...this.getSubdirs(browsersRoot, 'firefox-')
      ];
    }

    return [];
  }

  async uninstallBrowserComponent(target) {
    const allowedTargets = new Set(['chromium', 'firefox', 'patchright']);
    if (!allowedTargets.has(target)) {
      return { success: false, error: `unsupported_uninstall_target:${target}` };
    }

    if (target === 'patchright') {
      const runtime = this.getPythonRuntime();
      if (runtime.source !== 'prismenv') {
        return {
          success: false,
          output: '',
          error: `packaged_python_unavailable:${runtime.error || runtime.source}`,
          browserRuntimeInfo: this.getBrowserRuntimeInfo()
        };
      }

      const env = this.buildPythonEnv({
        ...process.env,
        PLAYWRIGHT_BROWSERS_PATH: this.getBrowsersRoot(),
        LAOMA_AUTOMATION_RUNTIME: this.runtimeSettings.automationRuntime
      });

      const result = await this.runManagedCommand(
        this.getPythonPath(),
        ['-m', 'pip', 'uninstall', '-y', target],
        { env, logPrefix: `pip:remove:${target}` }
      );

      return {
        success: result.success,
        output: result.stdout,
        error: result.error,
        browserRuntimeInfo: this.getBrowserRuntimeInfo()
      };
    }

    const removalTargets = this.getBrowserAssetRemovalTargets(target);
    const removedPaths = [];

    for (const candidate of removalTargets) {
      if (!candidate || !fs.existsSync(candidate)) {
        continue;
      }
      fs.rmSync(candidate, { recursive: true, force: true });
      removedPaths.push(candidate);
    }

    if (target === 'firefox') {
      const nextPreferences = this.normalizePlatformBrowserPreferences(
        this.runtimeSettings.platformBrowserPreferences
      );
      let preferencesChanged = false;

      for (const platform of Object.keys(nextPreferences)) {
        if (nextPreferences[platform] === 'firefox') {
          nextPreferences[platform] = 'chromium';
          preferencesChanged = true;
        }
      }

      if (preferencesChanged) {
        this.saveRuntimeSettings({
          platformBrowserPreferences: nextPreferences
        });
      }
    }

    return {
      success: true,
      removedPaths,
      browserRuntimeInfo: this.getBrowserRuntimeInfo()
    };
  }

  runManagedCommand(command, args, options = {}) {
    const { cwd = this.getResourcesRoot(), env = process.env, logPrefix = 'command' } = options;

    return new Promise((resolve) => {
      let stdout = '';
      let stderr = '';
      let settled = false;

      const child = spawn(command, args, {
        cwd,
        env,
        windowsHide: true
      });

      const finish = (result) => {
        if (settled) {
          return;
        }
        settled = true;
        resolve(result);
      };

      child.stdout?.on('data', (chunk) => {
        const text = chunk.toString();
        stdout += text;
        log.info(`[${logPrefix}] ${text.trimEnd()}`);
      });

      child.stderr?.on('data', (chunk) => {
        const text = chunk.toString();
        stderr += text;
        log.warn(`[${logPrefix}] ${text.trimEnd()}`);
      });

      child.on('error', (error) => {
        finish({
          success: false,
          code: -1,
          stdout,
          stderr,
          error: error.message
        });
      });

      child.on('close', (code) => {
        finish({
          success: code === 0,
          code,
          stdout,
          stderr,
          error: code === 0 ? null : (stderr.trim() || stdout.trim() || `command_failed:${code}`)
        });
      });
    });
  }

  async installBrowserComponent(target) {
    const allowedTargets = new Set(['chromium', 'firefox', 'patchright']);
    if (!allowedTargets.has(target)) {
      return { success: false, error: `unsupported_target:${target}` };
    }

    const pythonPath = this.getPythonPath();
    const browsersRoot = this.getBrowsersRoot();
    fs.mkdirSync(browsersRoot, { recursive: true });

    const env = this.buildPythonEnv({
      ...process.env,
      PLAYWRIGHT_BROWSERS_PATH: browsersRoot,
      LAOMA_AUTOMATION_RUNTIME: this.runtimeSettings.automationRuntime
    });

    if (target === 'patchright') {
      const runtime = this.getPythonRuntime();
      if (runtime.source !== 'prismenv') {
        return {
          success: false,
          output: '',
          error: `packaged_python_unavailable:${runtime.error || runtime.source}`,
          browserRuntimeInfo: this.getBrowserRuntimeInfo()
        };
      }

      const result = await this.runManagedCommand(
        pythonPath,
        ['-m', 'pip', 'install', target],
        { env, logPrefix: `pip:${target}` }
      );

      return {
        success: result.success,
        output: result.stdout,
        error: result.error,
        browserRuntimeInfo: this.getBrowserRuntimeInfo()
      };
    }

    if (target === 'chromium') {
      const installResult = await this.installHibbikiChromium();
      return {
        success: installResult.success,
        output: installResult.stdout,
        error: installResult.error,
        browserRuntimeInfo: this.getBrowserRuntimeInfo()
      };
    }

    const patchrightInfo = this.getPythonPackageInfo('patchright');
    if (!patchrightInfo.installed) {
      const runtimeInstall = await this.runManagedCommand(
        pythonPath,
        ['-m', 'pip', 'install', '--upgrade', '--force-reinstall', 'patchright==1.59.1'],
        { env, logPrefix: 'pip:patchright' }
      );

      if (!runtimeInstall.success) {
        return {
          success: false,
          output: runtimeInstall.stdout,
          error: runtimeInstall.error,
          browserRuntimeInfo: this.getBrowserRuntimeInfo()
        };
      }
    }

    const preferredRuntime = 'patchright';
    const installCommand = ['-m', 'patchright', 'install', target];

    const installResult = await this.runManagedCommand(
      pythonPath,
      installCommand,
      { env, logPrefix: `${preferredRuntime}:${target}` }
    );

    return {
      success: installResult.success,
      output: installResult.stdout,
      error: installResult.error,
      browserRuntimeInfo: this.getBrowserRuntimeInfo()
    };
  }

  getAppIconPath() {
    return this.resolveFirstPath([
      path.join(app.getAppPath(), 'icon.ico'),
      path.join(process.resourcesPath, 'icon.ico'),
      path.join(__dirname, '..', '..', 'icon.ico')
    ]);
  }

  setupTray() {
    if (this.tray || !this.appIconPath) {
      return;
    }

    this.tray = new Tray(this.appIconPath);
    this.tray.setToolTip('老马AI工作台');
    this.refreshTrayMenu();

    this.tray.on('click', () => {
      this.showMainWindow();
    });

    this.tray.on('double-click', () => {
      this.showMainWindow();
    });
  }

  refreshTrayMenu() {
    if (!this.tray) {
      return;
    }

    this.tray.setContextMenu(Menu.buildFromTemplate([
      {
        label: 'Open main window',
        click: () => this.showMainWindow()
      },
      {
        label: 'Open settings',
        click: () => this.createSettingsWindow()
      },
      { type: 'separator' },
      {
        label: 'Quit and stop all processes',
        click: () => {
          void this.quitApplication();
        }
      }
    ]));
  }

  showMainWindow() {
    if (!this.mainWindow || this.mainWindow.isDestroyed()) {
      this.createMainWindow();
      return;
    }

    if (this.mainWindow.isMinimized()) {
      this.mainWindow.restore();
    }

    this.mainWindow.show();
    this.mainWindow.focus();
  }

  getSupervisorStatePath() {
    if (this.supervisorStatePath) {
      return this.supervisorStatePath;
    }
    const explicitPath = process.env.LAOMA_SUPERVISOR_STATE_PATH;
    if (explicitPath) {
      this.supervisorStatePath = explicitPath;
      return this.supervisorStatePath;
    }
    this.supervisorStatePath = path.join(app.getPath('userData'), 'supervisor-state.json');
    return this.supervisorStatePath;
  }

  readSupervisorState() {
    try {
      const raw = fs.readFileSync(this.getSupervisorStatePath(), 'utf8');
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch (error) {
      return null;
    }
  }

  async waitForSupervisorState(timeoutMs = 30000, pollIntervalMs = 300) {
    const deadline = Date.now() + timeoutMs;
    let lastState = null;
    while (Date.now() < deadline) {
      const state = this.readSupervisorState();
      if (state && Number.isInteger(state.apiPort) && state.apiPort > 0) {
        lastState = state;
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }
    if (!lastState) {
      throw new Error('Supervisor state file did not appear within timeout (动态端口发现失败)');
    }
    this.supervisorApiPort = lastState.apiPort;
    this.supervisorLaunchToken = lastState.launchToken || null;

    // 从状态文件同步服务端口（权威来源仍是 /api/status，这里先做引导）
    const servicePorts = lastState.servicePorts || {};
    if (Number.isInteger(servicePorts.backend) && servicePorts.backend > 0) {
      log.info(`Bootstrap backend port from supervisor state: ${this.backendPort || 'unset'} -> ${servicePorts.backend}`);
      this.backendPort = servicePorts.backend;
    }
    if (Number.isInteger(servicePorts['automation-worker']) && servicePorts['automation-worker'] > 0) {
      log.info(`Bootstrap automation-worker port from supervisor state: ${this.automationWorkerPort || 'unset'} -> ${servicePorts['automation-worker']}`);
      this.automationWorkerPort = servicePorts['automation-worker'];
    }
    log.info('Supervisor state discovered:', { apiPort: this.supervisorApiPort, launchToken: Boolean(this.supervisorLaunchToken) });
    return lastState;
  }

  cleanupStaleSupervisorFromState() {
    const state = this.readSupervisorState();
    if (!state || !Number.isInteger(state.pid) || state.pid <= 0) {
      return;
    }
    if (state.pid === process.pid) {
      return;
    }
    const details = this.getProcessDetails(state.pid);
    const commandLine = String(details?.commandLine || '').toLowerCase();
    const executablePath = path.normalize(String(details?.executablePath || '')).toLowerCase();
    const isSupervisorProcess = commandLine.includes('supervisor') || executablePath.includes('supervisor');
    if (!isSupervisorProcess) {
      return;
    }
    if (this.terminateProcessByPid(state.pid)) {
      log.warn(`Terminated stale supervisor from previous state file (pid ${state.pid})`);
    }
  }

  getSupervisorApiPort() {
    return this.supervisorApiPort || 7002;
  }

  async getSupervisorDiagnostics(timeoutMs = 5000) {
    try {
      const payload = await this.requestSupervisor('/api/diagnostics', 'GET', timeoutMs);
      return payload?.data || payload || null;
    } catch (error) {
      log.warn('Failed to fetch supervisor diagnostics:', error);
      return null;
    }
  }

  getVersionInfo() {
    // 双版本体系：桌面壳版本 + 内置服务版本（参考 dsh-desktop 的 version-info）
    return buildVersionInfo(app.getVersion(), this.getResourcesRoot(), this.repoRoot);
  }

  async requestSupervisor(pathname, method = 'GET', timeoutMs = 20000) {
    const http = require('http');

    return new Promise((resolve, reject) => {
      const req = http.request({
        hostname: '127.0.0.1',
        port: this.getSupervisorApiPort(),
        path: pathname,
        method
      }, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            resolve(data ? JSON.parse(data) : {});
          } catch (error) {
            reject(error);
          }
        });
      });

      req.on('error', reject);
      req.setTimeout(timeoutMs, () => {
        req.destroy();
        reject(new Error(`Supervisor request timeout: ${pathname}`));
      });
      req.end();
    });
  }

  syncManagedServicePortsFromStatus(statusPayload) {
    const status = statusPayload?.data || statusPayload || {};
    const backendStatus = status.backend || {};
    const workerStatus = status.automation_worker || status.worker || {};
    const parsePort = (value) => {
      const parsed = Number.parseInt(String(value || ''), 10);
      return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
    };

    const nextBackendPort = parsePort(backendStatus.port);
    const nextWorkerPort = parsePort(workerStatus.port);

    if (nextBackendPort && nextBackendPort !== this.backendPort) {
      log.info(`Syncing backend port from supervisor status: ${this.backendPort || 'unset'} -> ${nextBackendPort}`);
      this.backendPort = nextBackendPort;
    }

    if (nextWorkerPort && nextWorkerPort !== this.automationWorkerPort) {
      log.info(`Syncing automation-worker port from supervisor status: ${this.automationWorkerPort || 'unset'} -> ${nextWorkerPort}`);
      this.automationWorkerPort = nextWorkerPort;
    }

    if (nextBackendPort) {
      const backendUrl = this.getBackendBaseUrl();
      const backendApiBaseUrl = this.getBackendApiBaseUrl();
      process.env.BACKEND_PORT = String(this.getBackendPort());
      process.env.LAOMA_BACKEND_PORT = process.env.BACKEND_PORT;
      process.env.LAOMA_BACKEND_URL = backendUrl;
      process.env.NEXT_PUBLIC_LAOMA_BACKEND_URL = backendUrl;
      process.env.NEXT_PUBLIC_BACKEND_URL = backendUrl;
      process.env.NEXT_PUBLIC_API_URL = backendUrl;
      process.env.MANUS_API_BASE_URL = backendApiBaseUrl;
      process.env.AGENT_API_BASE_URL = backendApiBaseUrl;
    }

    if (nextWorkerPort) {
      process.env.AUTOMATION_WORKER_PORT = String(this.getAutomationWorkerPort());
      process.env.LAOMA_AUTOMATION_WORKER_PORT = process.env.AUTOMATION_WORKER_PORT;
    }

    return status;
  }

  async getSupervisorStatus(timeoutMs = 5000) {
    const statusPayload = await this.requestSupervisor('/api/status', 'GET', timeoutMs);
    this.syncManagedServicePortsFromStatus(statusPayload);
    return statusPayload;
  }

  async requestSupervisorRestartAll(timeoutMs = 30000) {
    let lastError = null;

    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        return await this.requestSupervisor('/api/restart', 'POST', timeoutMs);
      } catch (error) {
        lastError = error;
        const message = String(error?.message || '');
        const isTimeout = message.includes('Supervisor request timeout: /api/restart');

        if (!isTimeout) {
          throw error;
        }

        log.warn(`Supervisor restart request timed out on attempt ${attempt + 1}; probing restart state...`);

        try {
          const restartState = await this.requestSupervisor('/api/restart-status', 'GET', 5000);
          if (restartState?.data?.restart_in_progress) {
            return { status: 'accepted', message: 'Restart already in progress' };
          }
        } catch (probeError) {
          log.warn('Failed to probe supervisor restart state after timeout:', probeError);
        }

        if (attempt === 0) {
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
      }
    }

    throw lastError || new Error('Supervisor restart request failed');
  }

  async waitForSupervisorServices(timeoutMs = 60000, pollIntervalMs = 1000) {
    const deadline = Date.now() + timeoutMs;

    while (Date.now() < deadline) {
      try {
        const restartState = await this.requestSupervisor('/api/restart-status', 'GET', 5000);
        const statusPayload = await this.getSupervisorStatus(5000);
        const status = statusPayload?.data || {};
        const isServiceReady = (service, { allowDisabled = false, optional = false } = {}) => {
          if (!service) {
            return optional;
          }
          if (service.running || service.external) {
            return true;
          }
          if (allowDisabled && (service.configured === false || service.source === 'disabled')) {
            return true;
          }
          return false;
        };

        const backendReady = isServiceReady(status.backend);
        const workerReady = isServiceReady(status.automation_worker || status.worker);
        const celeryReady = isServiceReady(status.celery_worker || status.celery);
        const restartInProgress = Boolean(restartState?.data?.restart_in_progress);

        // Hermes sidecars are non-blocking for desktop startup. They may be
        // absent, disabled, or recover asynchronously, but the packaged app
        // should still finish booting once the core automation stack is ready.
        if (
          backendReady &&
          workerReady &&
          celeryReady &&
          !restartInProgress
        ) {
          return true;
        }
      } catch (error) {
        log.warn('Waiting for supervisor services failed; retrying...', error);
      }

      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
    }

    throw new Error('Timed out waiting for supervisor services to become healthy');
  }

  async stopManagedServices() {
    if (this.supervisorProcess && !this.supervisorProcess.killed) {
      try {
        await this.requestSupervisor('/api/stop', 'POST');
      } catch (error) {
        log.warn('Failed to stop managed services via supervisor API:', error);
      }
    }

    this.cleanup();
  }

  async restartManagedServices() {
    log.info('Restarting managed service stack...');
    await this.stopManagedServices();
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await this.startServices();
    this.servicesStarted = true;
    log.info('Managed service stack restarted successfully');
    return { success: true };
  }

  async quitApplication() {
    if (this.isQuitting) {
      return { success: true };
    }

    this.isQuitting = true;
    this.isRestarting = false;
    log.info('Quitting application and stopping all processes...');

    try {
      await this.stopManagedServices();
      if (this.tray) {
        this.tray.destroy();
        this.tray = null;
      }
      app.quit();
      return { success: true };
    } catch (error) {
      this.isQuitting = false;
      log.error('Failed to quit application cleanly:', error);
      return { success: false, error: error.message };
    }
  }

  scheduleAppRestart() {
    const relaunchEnv = {
      ...process.env,
      PLAYWRIGHT_HEADLESS: this.runtimeSettings.browserHeadless ? 'true' : 'false',
      LAOMA_AUTOMATION_RUNTIME: this.runtimeSettings.automationRuntime
    };
    this.applyPlatformBrowserPreferenceEnv(relaunchEnv, this.runtimeSettings.platformBrowserPreferences || {});
    this.applyPlatformProxyPreferenceEnv(relaunchEnv, this.runtimeSettings.platformProxyPreferences || {});

    if (this.isDev) {
      relaunchEnv.LAOMA_START_SERVICES = process.env.LAOMA_START_SERVICES || '1';
      relaunchEnv.LAOMA_START_FRONTEND = process.env.LAOMA_START_FRONTEND || '1';

      const appPath = app.getAppPath();
      const child = spawn(process.execPath, [appPath], {
        cwd: appPath,
        env: relaunchEnv,
        detached: true,
        stdio: 'ignore',
        windowsHide: true
      });
      child.unref();
      log.info('Scheduled dev app restart via detached Electron process');
      return;
    }

    app.relaunch({
      execPath: process.execPath,
      args: process.argv.slice(1)
    });
    log.info('Scheduled packaged app restart via app.relaunch');
  }

  getServiceExe(name) {
    if (this.isDev) {
      return null;
    }
    const candidates = [
      path.join(process.resourcesPath, 'services', name, `${name}.exe`),
      path.join(process.resourcesPath, 'services', `${name}.exe`)
    ];
    return this.resolveFirstPath(candidates) || null;
  }

  /**
   * 云端 SaaS 根地址(不含 `/cloud` 前缀)。
   *
   * 优先级:
   *   1. 进程环境变量 `CLOUD_URL` / `LAOMA_CLOUD_BASE_URL` —— 用户自建云端时用
   *   2. 安装包内置值 `package.json` 的 `laomaCloudUrl` —— 官方云端,打包时写死
   *
   * 约定:后端(`cloud_gateway.py` / `billing_client.py` / `points_client.py`)与
   * 前端(`client-gateway.ts`)都约定这里给的是**根地址**,`/cloud` 前缀由各自补,
   * 所以这里不要带 `/cloud` 后缀。
   */
  getCloudBaseUrl() {
    const fromEnv = String(process.env.CLOUD_URL || process.env.LAOMA_CLOUD_BASE_URL || '').trim();
    if (fromEnv) {
      return fromEnv.replace(/\/+$/, '');
    }

    let packaged = '';
    try {
      // ⚠️ 这里**不能**用 `require('../package.json')`。
      // 打包后本文件位于 `app.asar/src/main/index.js`，`'../package.json'` 解析到
      // `app.asar/src/package.json` —— 不存在，require 抛 MODULE_NOT_FOUND，
      // 于是 laomaCloudUrl **永远读不到**，getCloudBaseUrl() 返回空串，
      // 后端拿不到 CLOUD_URL → 云端地址退回占位域名 `api.prism.local` →
      // 云端订阅永远 community、注册码「同步到云端」直接 502、
      // 云端 AI / 云端生图全部退回本地模式（商业闭环整条链断在这里）。
      //
      // 正确做法：从 `app.getAppPath()` 拼根 package.json
      // （打包态 = `...\resources\app.asar`，开发态 = `desktop-electron` 目录），
      // electron-builder 的 extraMetadata 会把 laomaCloudUrl 合并进那一份。
      // fs 读 asar 内文件是透明的，dev / packaged 两条路都成立。
      const pkgPath = path.join(app.getAppPath(), 'package.json');
      const pkg = readJsonFileSafely(pkgPath);
      packaged = String((pkg && pkg.laomaCloudUrl) || '').trim();
    } catch (error) {
      log.warn('Unable to read laomaCloudUrl from package.json:', error && error.message);
    }

    if (!packaged) {
      log.warn('Cloud base URL is not configured; cloud features stay in local mode.');
      return '';
    }
    return packaged.replace(/\/+$/, '');
  }

  buildServiceEnv() {
    const browsersRoot = this.getBrowsersRoot();
    const backendUrl = this.getBackendBaseUrl();
    const backendApiBaseUrl = this.getBackendApiBaseUrl();
    const backendPort = String(this.getBackendPort());
    const automationWorkerPort = String(this.getAutomationWorkerPort());
    const pythonPath = this.getPythonPath();
    log.info('Preparing service environment...');
    log.info('  - Browsers Root:', browsersRoot);
    log.info('  - Browsers Root exists:', fs.existsSync(browsersRoot));

    const appRoot = this.getResourcesRoot();
    const env = {
      ...process.env,
      PYTHONUTF8: '1',
      PYTHONIOENCODING: 'utf-8',
      LAOMA_APP_ROOT: appRoot,
      LAOMA_RESOURCES_PATH: appRoot,
      PRISM_HERMES_PYTHON: pythonPath,
      PRISM_RUNTIME_SETTINGS_PATH: this.getRuntimeSettingsPath(),
      PLAYWRIGHT_BROWSERS_PATH: browsersRoot,
      PLAYWRIGHT_HEADLESS: this.runtimeSettings.browserHeadless ? 'true' : 'false',
      LAOMA_AUTOMATION_RUNTIME: this.runtimeSettings.automationRuntime,
      BACKEND_PORT: backendPort,
      LAOMA_BACKEND_PORT: backendPort,
      AUTOMATION_WORKER_PORT: automationWorkerPort,
      LAOMA_AUTOMATION_WORKER_PORT: automationWorkerPort,
      LAOMA_BACKEND_URL: backendUrl,
      SUPERVISOR_KILL_PORT_CONFLICT: '0',
      NEXT_PUBLIC_LAOMA_BACKEND_URL: backendUrl,
      NEXT_PUBLIC_BACKEND_URL: backendUrl,
      NEXT_PUBLIC_API_URL: backendUrl,
      MANUS_API_BASE_URL: backendApiBaseUrl,
      AGENT_API_BASE_URL: backendApiBaseUrl
    };

    // 云端 SaaS 地址注入后端运行时环境(后端自己拼 /cloud 前缀)
    const cloudBaseUrl = this.getCloudBaseUrl();
    if (cloudBaseUrl) {
      env.CLOUD_URL = cloudBaseUrl;
      env.LAOMA_CLOUD_BASE_URL = cloudBaseUrl;
      log.info('  - Cloud Base URL:', cloudBaseUrl);
    } else {
      log.warn('  - Cloud Base URL: <not configured> (cloud features fall back to local mode)');
    }

    const pythonEnv = this.buildPythonEnv(env);
    Object.assign(env, pythonEnv);
    this.applyPlatformBrowserPreferenceEnv(env, this.runtimeSettings.platformBrowserPreferences || {});
    this.applyPlatformProxyPreferenceEnv(env, this.runtimeSettings.platformProxyPreferences || {});
    // ⚠️ 数据目录：
    //   - dev 态：仍然「环境变量优先，没有才用仓库内目录」（开发时想在项目内落数据的人
    //     可以自己设 LAOMA_DATA_DIR）。
    //   - packaged 态：**恒为** userData\data，**不接受进程环境变量覆盖**。
    //     外部环境里只要残留一个同名变量，用户数据就会被劫持到别处
    //     （实测：机器上有 LAOMA_DATA_DIR=D:\...\data 时，客户端把注册码写进了
    //       源码仓库目录，而不是跟着用户走的 %APPDATA%\laoma-ai-workbench\data），
    //     与「装在哪就在哪用、卸载即清干净」的预期完全不符。
    if (this.isDev) {
      if (!env.LAOMA_DATA_DIR) {
        const devDataDir = path.join(this.repoRoot, 'prism_backend');
        env.LAOMA_DATA_DIR = devDataDir;
        log.info('  - LAOMA_DATA_DIR (dev):', devDataDir);
      }
    } else {
      if (env.LAOMA_DATA_DIR) {
        log.warn(
          '  - Ignoring inherited LAOMA_DATA_DIR in packaged mode:',
          env.LAOMA_DATA_DIR
        );
      }
      const userDataDir = app.getPath('userData');
      const dataDir = path.join(userDataDir, 'data');
      if (!fs.existsSync(dataDir)) {
        fs.mkdirSync(dataDir, { recursive: true });
      }
      env.LAOMA_DATA_DIR = dataDir;
      const hermesRoot = path.join(userDataDir, 'hermes');
      const hermesHome = path.join(hermesRoot, 'home');
      const hermesWebUiState = path.join(hermesRoot, 'webui');
      const hermesWorkspace = path.join(hermesRoot, 'workspace');
      const hermesConfigRoot = path.join(userDataDir, 'config');
      [hermesHome, hermesWebUiState, hermesWorkspace, hermesConfigRoot].forEach((dirPath) => {
        if (!fs.existsSync(dirPath)) {
          fs.mkdirSync(dirPath, { recursive: true });
        }
      });
      env.PRISM_HERMES_HOME = hermesHome;
      env.PRISM_HERMES_WEBUI_STATE_DIR = hermesWebUiState;
      env.PRISM_HERMES_WORKSPACE = hermesWorkspace;
      env.PRISM_HERMES_CONFIG_ROOT = hermesConfigRoot;
      log.info('  - LAOMA_DATA_DIR:', dataDir);
    }
    // 开发态跳过 Hermes 能力门禁：本地通常没有注册码，
    // 否则 supervisor 会把 dashboard / webui / gateway 全拦掉，没法调试。
    // 打包态不设这个变量 → 限制功能版用户不会启动 Hermes sidecar。
    if (this.isDev) {
      env.LAOMA_HERMES_SKIP_ENTITLEMENT_GATE = '1';
    }
    if (!env.PLAYWRIGHT_AUTO_INSTALL) {
      env.PLAYWRIGHT_AUTO_INSTALL = this.isDev ? '1' : '0';
    }
    if (!env.ENABLE_OCR_RESCUE) {
      env.ENABLE_OCR_RESCUE = '1';
    }
    if (!env.ENABLE_SELENIUM_RESCUE) {
      env.ENABLE_SELENIUM_RESCUE = '1';
    }
    if (!env.ENABLE_SELENIUM_DEBUG) {
      env.ENABLE_SELENIUM_DEBUG = '1';
    }

    const chromePath = this.resolveChromePath(browsersRoot);
    if (chromePath) {
      env.LOCAL_CHROME_PATH = chromePath;
      log.info('  - Chrome Path:', chromePath);
    } else {
      log.warn('  - Chrome Path: NOT FOUND');
    }

    const firefoxPath = this.resolveFirefoxPath(browsersRoot);
    if (firefoxPath) {
      env.LOCAL_FIREFOX_PATH = firefoxPath;
      log.info('  - Firefox Path:', firefoxPath);
    } else {
      log.warn('  - Firefox Path: NOT FOUND');
    }

    log.info('Service environment prepared');
    return env;
  }

  isPortInUse(port, host = '127.0.0.1', timeoutMs = 500) {
    return new Promise((resolve) => {
      const socket = new net.Socket();
      let settled = false;

      const finish = (inUse) => {
        if (settled) {
          return;
        }
        settled = true;
        socket.destroy();
        resolve(inUse);
      };

      socket.setTimeout(timeoutMs);
      socket.once('connect', () => finish(true));
      socket.once('timeout', () => finish(false));
      socket.once('error', () => finish(false));
      socket.connect(port, host);
    });
  }

  canBindPort(port, host = '127.0.0.1') {
    return new Promise((resolve) => {
      const server = net.createServer();
      let settled = false;

      const finish = (result) => {
        if (settled) {
          return;
        }
        settled = true;
        try {
          server.close(() => resolve(result));
        } catch (error) {
          resolve(result);
        }
      };

      server.once('error', () => finish(false));
      server.once('listening', () => finish(true));
      server.listen({
        host,
        port,
        exclusive: true
      });
    });
  }

  requestLocalJson(port, pathName, timeoutMs = 2000) {
    const http = require('http');

    return new Promise((resolve, reject) => {
      const req = http.request({
        hostname: '127.0.0.1',
        port,
        path: pathName,
        method: 'GET'
      }, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            resolve(data ? JSON.parse(data) : {});
          } catch (error) {
            reject(error);
          }
        });
      });

      req.on('error', reject);
      req.setTimeout(timeoutMs, () => {
        req.destroy();
        reject(new Error(`Local request timeout: ${port}${pathName}`));
      });
      req.end();
    });
  }

  async isPrismBackendOnPort(port) {
    if (!(await this.isPortInUse(port))) {
      return false;
    }

    try {
      const payload = await this.requestLocalJson(port, '/health', 2000);
      return String(payload?.status || '').toLowerCase() === 'healthy' && Boolean(payload?.version);
    } catch (error) {
      return false;
    }
  }

  async isAutomationWorkerOnPort(port) {
    if (!(await this.isPortInUse(port))) {
      return false;
    }

    try {
      const payload = await this.requestLocalJson(port, '/health', 2000);
      return String(payload?.status || '').toLowerCase() === 'ok' && payload?.service === 'automation-worker';
    } catch (error) {
      return false;
    }
  }

  async prepareManagedServicePorts() {
    const configuredWorkerPort = this.getConfiguredAutomationWorkerPort();
    const configuredBackendPort = this.getConfiguredBackendPort();
    const reservedPorts = new Set();

    this.backendPort = await this.resolveManagedPort(
      configuredBackendPort,
      this.isPrismBackendOnPort.bind(this),
      reservedPorts
    );
    reservedPorts.add(this.backendPort);

    this.automationWorkerPort = await this.resolveManagedPort(
      configuredWorkerPort,
      this.isAutomationWorkerOnPort.bind(this),
      reservedPorts
    );

    log.info('Managed service ports prepared:', {
      backendPort: this.backendPort,
      automationWorkerPort: this.automationWorkerPort
    });
  }

  listListeningPidsByPort(port) {
    if (process.platform !== 'win32') {
      return [];
    }

    try {
      const psCommand = [
        '$ErrorActionPreference = "SilentlyContinue"',
        `$pids = Get-NetTCPConnection -State Listen -LocalPort ${Number(port)} | Select-Object -ExpandProperty OwningProcess -Unique`,
        'if ($pids) { $pids | ConvertTo-Json -Compress }'
      ].join('; ');
      const result = spawnSync('powershell.exe', ['-NoProfile', '-Command', psCommand], {
        encoding: 'utf8',
        windowsHide: true
      });

      if (result.error || result.status !== 0) {
        return [];
      }

      const raw = String(result.stdout || '').trim();
      if (!raw) {
        return [];
      }

      const parsed = JSON.parse(raw);
      const values = Array.isArray(parsed) ? parsed : [parsed];
      return values
        .map((value) => Number.parseInt(value, 10))
        .filter((value) => Number.isInteger(value) && value > 0);
    } catch (error) {
      log.warn(`Failed to inspect listening PIDs on port ${port}:`, error);
      return [];
    }
  }

  getSupervisorResourceMarkers() {
    const candidates = [
      path.join(process.resourcesPath, 'supervisor'),
      path.join(this.repoRoot, 'desktop-electron', 'resources', 'supervisor')
    ];

    return [...new Set(
      candidates
        .filter(Boolean)
        .map((candidate) => path.normalize(candidate).toLowerCase())
    )];
  }

  getManagedServiceResourceMarkers() {
    const candidates = [
      this.repoRoot,
      path.join(this.repoRoot, 'prism_backend'),
      path.join(this.repoRoot, 'tools', 'hermes-agent'),
      path.join(this.repoRoot, 'tools', 'hermes-webui'),
      path.join(process.resourcesPath, 'prism_backend'),
      path.join(process.resourcesPath, 'tools', 'hermes-agent'),
      path.join(process.resourcesPath, 'tools', 'hermes-webui'),
      path.join(process.resourcesPath, 'services', 'backend'),
      path.join(process.resourcesPath, 'supervisor'),
      path.join(this.repoRoot, 'desktop-electron', 'resources', 'supervisor')
    ];

    return [...new Set(
      candidates
        .filter(Boolean)
        .map((candidate) => path.normalize(candidate).toLowerCase())
    )];
  }

  listRepoManagedServicePids() {
    if (process.platform !== 'win32') {
      return [];
    }

    try {
      const markers = this.getManagedServiceResourceMarkers()
        .map((marker) => `'${marker.replace(/'/g, "''")}'`)
        .join(', ');
      const psCommand = [
        '$ErrorActionPreference = "SilentlyContinue"',
        `$markers = @(${markers})`,
        '$keywords = @(',
        "  'fastapi_app\\\\run.py',",
        "  'automation_worker\\\\worker.py',",
        "  'tools\\\\hermes-webui\\\\server.py',",
        "  'hermes_cli.main',",
        "  'celery_app',",
        "  'supervisor.py'",
        ')',
        '$pids = Get-CimInstance Win32_Process | Where-Object {',
        '  $name = [string]$_.Name',
        '  $cmd = [string]$_.CommandLine',
        '  $exe = [string]$_.ExecutablePath',
        '  $cmdLower = $cmd.ToLower()',
        '  $exeLower = $exe.ToLower()',
        '  $belongsToRepo = $false',
        '  foreach ($marker in $markers) {',
        '    if (($cmdLower -and $cmdLower.Contains($marker)) -or ($exeLower -and $exeLower.Contains($marker))) {',
        '      $belongsToRepo = $true',
        '      break',
        '    }',
        '  }',
        '  if (-not $belongsToRepo) { return $false }',
        "  $serviceByName = $name.ToLower() -in @('backend.exe', 'supervisor.exe')",
        '  $serviceByCommand = $false',
        '  foreach ($keyword in $keywords) {',
        '    if ($cmdLower -and $cmdLower.Contains($keyword)) {',
        '      $serviceByCommand = $true',
        '      break',
        '    }',
        '  }',
        '  $serviceByName -or $serviceByCommand',
        '} | Select-Object -ExpandProperty ProcessId -Unique',
        'if ($pids) { $pids | ConvertTo-Json -Compress }'
      ].join('; ');
      const result = spawnSync('powershell.exe', ['-NoProfile', '-Command', psCommand], {
        encoding: 'utf8',
        windowsHide: true
      });

      if (result.error || result.status !== 0) {
        return [];
      }

      const raw = String(result.stdout || '').trim();
      if (!raw) {
        return [];
      }

      const parsed = JSON.parse(raw);
      const values = Array.isArray(parsed) ? parsed : [parsed];
      return values
        .map((value) => Number.parseInt(value, 10))
        .filter((value) => Number.isInteger(value) && value > 0);
    } catch (error) {
      log.warn('Failed to inspect repo managed service processes:', error);
      return [];
    }
  }

  listRepoSupervisorPids() {
    if (process.platform !== 'win32') {
      return [];
    }

    try {
      const markers = this.getSupervisorResourceMarkers()
        .map((marker) => `'${marker.replace(/'/g, "''")}'`)
        .join(', ');
      const psCommand = [
        '$ErrorActionPreference = "SilentlyContinue"',
        `$markers = @(${markers})`,
        '$pids = Get-CimInstance Win32_Process | Where-Object {',
        '  $name = [string]$_.Name',
        '  $cmd = [string]$_.CommandLine',
        '  $exe = [string]$_.ExecutablePath',
        '  $belongsToRepo = $false',
        '  foreach ($marker in $markers) {',
        '    if (($cmd -and $cmd.ToLower().Contains($marker)) -or ($exe -and $exe.ToLower().Contains($marker))) {',
        '      $belongsToRepo = $true',
        '      break',
        '    }',
        '  }',
        "  $looksLikeSupervisor = ($name.ToLower() -eq 'supervisor.exe') -or (($name.ToLower().StartsWith('python')) -and $cmd -and $cmd.ToLower().Contains('supervisor.py'))",
        '  $belongsToRepo -and $looksLikeSupervisor',
        '} | Select-Object -ExpandProperty ProcessId -Unique',
        'if ($pids) { $pids | ConvertTo-Json -Compress }'
      ].join('; ');
      const result = spawnSync('powershell.exe', ['-NoProfile', '-Command', psCommand], {
        encoding: 'utf8',
        windowsHide: true
      });

      if (result.error || result.status !== 0) {
        return [];
      }

      const raw = String(result.stdout || '').trim();
      if (!raw) {
        return [];
      }

      const parsed = JSON.parse(raw);
      const values = Array.isArray(parsed) ? parsed : [parsed];
      return values
        .map((value) => Number.parseInt(value, 10))
        .filter((value) => Number.isInteger(value) && value > 0);
    } catch (error) {
      log.warn('Failed to inspect repo supervisor processes:', error);
      return [];
    }
  }

  getProcessDetails(pid) {
    if (process.platform !== 'win32' || !Number.isInteger(pid) || pid <= 0) {
      return null;
    }

    try {
      const psCommand = [
        '$ErrorActionPreference = "SilentlyContinue"',
        `$proc = Get-CimInstance Win32_Process -Filter "ProcessId = ${pid}"`,
        'if ($proc) {',
        '  [PSCustomObject]@{',
        '    processId = $proc.ProcessId',
        '    name = $proc.Name',
        '    executablePath = $proc.ExecutablePath',
        '    commandLine = $proc.CommandLine',
        '  } | ConvertTo-Json -Compress',
        '}'
      ].join('; ');
      const result = spawnSync('powershell.exe', ['-NoProfile', '-Command', psCommand], {
        encoding: 'utf8',
        windowsHide: true
      });

      if (result.error || result.status !== 0) {
        return null;
      }

      const raw = String(result.stdout || '').trim();
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      log.warn(`Failed to inspect process details for PID ${pid}:`, error);
      return null;
    }
  }

  terminateProcessByPid(pid) {
    if (!Number.isInteger(pid) || pid <= 0) {
      return false;
    }

    try {
      execSync(`taskkill /F /T /PID ${pid}`, { stdio: 'ignore' });
      return true;
    } catch (error) {
      log.warn(`Failed to terminate PID ${pid}:`, error);
      return false;
    }
  }

  cleanupStaleSupervisorOnPort(port = 7002) {
    const candidatePids = new Set(this.listRepoSupervisorPids());
    for (const pid of this.listListeningPidsByPort(port)) {
      candidatePids.add(pid);
    }

    if (candidatePids.size === 0) {
      return;
    }

    const repoMarkers = this.getSupervisorResourceMarkers();
    const terminated = [];

    for (const pid of candidatePids) {
      const details = this.getProcessDetails(pid);
      const commandLine = String(details?.commandLine || '').toLowerCase();
      const executablePath = path.normalize(String(details?.executablePath || '')).toLowerCase();
      const isSupervisorProcess = commandLine.includes('supervisor') || executablePath.includes('supervisor');
      const belongsToRepo = repoMarkers.some((marker) => commandLine.includes(marker) || executablePath.includes(marker));

      if (!isSupervisorProcess || !belongsToRepo) {
        continue;
      }

      if (this.terminateProcessByPid(pid)) {
        terminated.push(pid);
      }
    }

    if (terminated.length > 0) {
      log.warn(`Terminated stale repo supervisor process(es) before startup: ${terminated.join(', ')}`);
    }
  }

  cleanupStaleManagedServices() {
    const terminated = [];

    for (const pid of this.listRepoManagedServicePids()) {
      if (this.terminateProcessByPid(pid)) {
        terminated.push(pid);
      }
    }

    if (terminated.length > 0) {
      log.warn(`Terminated stale repo managed service process(es) before startup: ${terminated.join(', ')}`);
    }
  }

  async startServices() {
    if (this.servicesStarted) {
      return;
    }

    this.cleanupStaleManagedServices();
    await this.prepareManagedServicePorts();
    console.log('Using supervisor to manage backend services...');
    log.info('Using supervisor to manage backend services...');
    this.startSupervisor();
    await this.waitForSupervisorState(30000);
    try {
      await this.waitForSupervisorServices(120000, 1500);
    } catch (error) {
      // 就绪探测超时：只 log 警告，不阻止 frontend 启动
      const diagnostics = await this.getSupervisorDiagnostics(5000);
      const summary = this.summarizeDiagnostics(diagnostics);
      log.warn('Supervisor services not fully healthy yet, continuing anyway:', error.message, summary || '');
    }
    await this.startFrontend(this.buildServiceEnv());
    this.servicesStarted = true;
  }

  summarizeDiagnostics(diagnostics) {
    if (!diagnostics?.services) {
      return '';
    }
    const failed = [];
    for (const [name, status] of Object.entries(diagnostics.services)) {
      const failure = status?.failure;
      if (failure) {
        const detail = String(failure.detail || '').slice(0, 160);
        failed.push(`${name}(${failure.count}次失败/${failure.restart_count || 0}次重启): ${detail}`);
      }
    }
    return failed.length > 0 ? `失败服务: ${failed.join('; ')}` : '';
  }

  startSupervisor() {
    if (this.supervisorProcess) {
      return;
    }

    this.ensurePrismenvConfig();
    this.cleanupStaleSupervisorFromState();
    this.cleanupStaleSupervisorOnPort(7002);
    const supervisorPaths = this.getSupervisorPaths();
    const supervisorExe = supervisorPaths.exePath;
    const supervisorScript = supervisorPaths.scriptPath;
    const pythonPath = this.getPythonPath();

    console.log('Supervisor exe:', supervisorExe);
    console.log('Supervisor script:', supervisorScript);
    log.info('Starting supervisor...');
    log.info('  - Supervisor exe:', supervisorExe);
    log.info('  - Supervisor script:', supervisorScript);
    log.info('  - Supervisor cwd:', supervisorPaths.cwd);
    log.info('  - Exe exists:', Boolean(supervisorExe && fs.existsSync(supervisorExe)));
    log.info('  - Script exists:', Boolean(supervisorScript && fs.existsSync(supervisorScript)));

    if (!supervisorExe && !supervisorScript) {
      throw new Error('Supervisor entrypoint not found in packaged resources or desktop-electron/resources/supervisor');
    }

    const launchCmd = supervisorExe || pythonPath;
    const launchArgs = supervisorExe ? [] : [supervisorScript];

    console.log('Supervisor launch command:', launchCmd, launchArgs);
    log.info('  - Launch Command:', launchCmd);
    log.info('  - Launch Args:', launchArgs);

    // 构建环境变量
    const env = this.buildServiceEnv();
    // 动态端口发现：supervisor 把 API 端口/服务端口/启动令牌写入状态文件
    env.LAOMA_SUPERVISOR_STATE_PATH = this.getSupervisorStatePath();

    this.supervisorProcess = spawn(launchCmd, launchArgs, {
      cwd: supervisorPaths.cwd || this.getResourcesRoot(),
      env: env,
      windowsHide: true
    });

    this.supervisorProcess.on('error', (error) => {
      console.error('Supervisor failed to start:', error);
      log.error('Supervisor failed to start:', error);
    });

    this.supervisorProcess.stdout?.on('data', (data) => {
      console.log('[Supervisor]', data.toString());
      log.info('[Supervisor]', data.toString());
    });

    this.supervisorProcess.stderr?.on('data', (data) => {
      console.error('[Supervisor Error]', data.toString());
      log.error('[Supervisor Error]', data.toString());
    });

    this.supervisorProcess.on('exit', (code) => {
      console.warn(`Supervisor exited with code: ${code}`);
      log.warn(`Supervisor exited with code: ${code}`);
      this.supervisorProcess = null;
      this.lastSupervisorExit = { code, at: Date.now() };
    });

    console.log('Supervisor started');
    log.info('Supervisor started');
  }

  async startRedis(env) {
    if (this.redisProcess) {
      return;
    }
    const redisPath = this.isDev
      ? (process.env.LAOMA_REDIS_PATH || 'redis-server')
      : path.join(process.resourcesPath, 'redis', 'redis-server.exe');

    log.info('Starting Redis...');
    log.info('  - Redis Path:', redisPath);
    log.info('  - Redis exists:', fs.existsSync(redisPath));
    log.info('  - Is Dev:', this.isDev);

    if (await this.isPortInUse(6379)) {
      log.warn('Redis already running on port 6379; skipping start.');
      return;
    }

    if (!this.isDev && !fs.existsSync(redisPath)) {
      log.error(`Redis executable not found: ${redisPath}`);
      return;
    }
    this.redisProcess = spawn(redisPath, [], {
      env,
      cwd: this.getResourcesRoot(),
      windowsHide: true
    });
    this.redisProcess.on('error', (error) => {
      log.error('Redis failed to start:', error);
      this.redisProcess = null;
    });
    this.redisProcess.stdout?.on('data', (data) => log.info('[Redis]', data.toString()));
    this.redisProcess.stderr?.on('data', (data) => log.error('[Redis Error]', data.toString()));
    this.redisProcess.on('exit', (code) => {
      log.warn(`Redis exited with code: ${code}`);
    });
  }

  async startAutomationWorker(env) {
    if (this.automationWorkerProcess) {
      return;
    }
    if (!this.automationWorkerPort) {
      await this.prepareManagedServicePorts();
    }
    const workerPort = this.getAutomationWorkerPort();
    if (await this.isAutomationWorkerOnPort(workerPort)) {
      log.warn(`Automation Worker already running on port ${workerPort}; skipping start.`);
      return;
    }
    const backendDir = this.getBackendDir();
    const workerExe = this.getServiceExe('automation-worker');
    const workerScript = path.join(backendDir, 'automation_worker', 'worker.py');

    log.info('Starting Playwright worker...');
    log.info('  - Backend Dir:', backendDir);
    log.info('  - Worker Exe:', workerExe || 'N/A');
    log.info('  - Worker Script:', workerScript);
    log.info('  - Script exists:', fs.existsSync(workerScript));

    if (!workerExe && !fs.existsSync(workerScript)) {
      log.error(`Playwright worker script not found: ${workerScript}`);
      return;
    }
    const pythonPath = this.getPythonPath();
    const launchCmd = workerExe || pythonPath;
    const launchArgs = workerExe ? [] : [workerScript];

    log.info('  - Launch Command:', launchCmd);
    log.info('  - Launch Args:', launchArgs.join(' '));

    this.automationWorkerProcess = spawn(launchCmd, launchArgs, {
      env: { ...env, PYTHONPATH: backendDir, AUTOMATION_WORKER_PORT: String(workerPort) },
      cwd: backendDir,
      windowsHide: true
    });
    this.automationWorkerProcess.stdout?.on('data', (data) => log.info('[Worker]', data.toString()));
    this.automationWorkerProcess.stderr?.on('data', (data) => log.error('[Worker Error]', data.toString()));
    this.automationWorkerProcess.on('exit', (code) => {
      log.warn(`Playwright worker exited with code: ${code}`);
    });
  }

  startCelery(env) {
    if (this.celeryProcess) {
      return;
    }
    const backendDir = this.getBackendDir();
    const celeryExe = this.getServiceExe('celery-worker');
    const pythonPath = this.getPythonPath();

    log.info('Starting Celery worker...');
    log.info('  - Backend Dir:', backendDir);
    log.info('  - Celery Exe:', celeryExe || 'N/A');
    log.info('  - Python Path:', pythonPath);

    if (process.platform === 'win32') {
      try {
        const powershellPath = this.resolveFirstPath([
          path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        ]) || 'powershell.exe';
        const killCmd = "Get-CimInstance Win32_Process | Where-Object { ($_.Name -match 'python|celery-worker') -and ($_.CommandLine -match 'fastapi_app.tasks.celery_app' -or $_.CommandLine -match 'prism-worker') } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }";
        execSync(`"${powershellPath}" -NoProfile -Command "${killCmd}"`, { stdio: 'ignore' });
        log.info('Existing Celery workers stopped (if any).');
      } catch (error) {
        log.warn('Failed to stop existing Celery workers.', error);
      }
    }


    const launchCmd = celeryExe || pythonPath;
    const launchArgs = celeryExe
      ? []
      : [
          '-m',
          'celery',
          '-A',
          'fastapi_app.tasks.celery_app',
          'worker',
          '--loglevel=info',
          '--pool=threads',
          '--concurrency=1000',
          '--hostname=prism-worker@electron'
        ];

    log.info('  - Launch Command:', launchCmd);
    log.info('  - Launch Args:', launchArgs.join(' '));

    const pythonPathEnv = [backendDir, env.PYTHONPATH].filter(Boolean).join(path.delimiter);
    const celeryEnv = { ...env, PYTHONPATH: pythonPathEnv };
    if (!celeryEnv.PYTHONUTF8) {
      celeryEnv.PYTHONUTF8 = '1';
    }
    if (!celeryEnv.PYTHONIOENCODING) {
      celeryEnv.PYTHONIOENCODING = 'utf-8';
    }
    if (!celeryEnv.FORKED_BY_MULTIPROCESSING) {
      celeryEnv.FORKED_BY_MULTIPROCESSING = '1';
    }
    this.celeryProcess = spawn(launchCmd, launchArgs, {
      env: celeryEnv,
      cwd: backendDir,
      windowsHide: true
    });
    this.celeryProcess.stdout?.on('data', (data) => log.info('[Celery]', data.toString()));
    this.celeryProcess.stderr?.on('data', (data) => log.error('[Celery Error]', data.toString()));
    this.celeryProcess.on('exit', (code) => {
      log.warn(`Celery exited with code: ${code}`);
    });
  }

  async startFrontend(env) {
    log.info('Starting frontend...');
    log.info(`  - this.frontendProcess: ${this.frontendProcess ? 'exists' : 'null'}`);
    log.info(`  - this.isDev: ${this.isDev}`);
    if (this.useExternalStack()) {
      this.frontendPort = this.getPreferredFrontendPort();
      log.info('External stack mode enabled; skipping frontend startup.');
      return;
    }
    const serviceEnv = env || this.buildServiceEnv();
    const preferredFrontendPort = this.getPreferredFrontendPort();

    if (this.frontendProcess) {
      log.info('Frontend process already exists; skipping start.');
      return;
    }

    if (this.isDev) {
      const shouldStartDevFrontend =
        process.env.LAOMA_START_FRONTEND === '1' ||
        process.env.LAOMA_START_SERVICES === '1';
      if (!shouldStartDevFrontend) {
        log.info('Dev frontend auto-start is disabled; skipping start.');
        return;
      }

      this.frontendPort = await this.findAvailablePort(preferredFrontendPort);

      const frontendDir = path.join(this.repoRoot, 'prism_frontend');
      log.info(`  - frontendDir: ${frontendDir}`);
      log.info(`  - frontendPort: ${this.frontendPort}`);

      const nextCli = path.join(frontendDir, 'node_modules', 'next', 'dist', 'bin', 'next');
      const launchCmd = this.getNodeCommand();
      const launchArgs = [nextCli, 'dev', '--webpack'];
      const backendUrl = this.getBackendBaseUrl();
      const frontendEnv = {
        ...serviceEnv,
        NODE_ENV: 'development',
        PORT: String(this.frontendPort),
        HOSTNAME: '127.0.0.1',
        NEXT_PUBLIC_BACKEND_URL: backendUrl,
        NEXT_PUBLIC_API_URL: backendUrl,
        NEXT_PUBLIC_LAOMA_BACKEND_URL: backendUrl,
        LAOMA_BACKEND_URL: backendUrl
      };

      log.info('Launching development frontend...');
      this.frontendProcess = spawn(launchCmd, launchArgs, {
        env: frontendEnv,
        cwd: frontendDir,
        windowsHide: true
      });
      this.frontendProcess.stdout?.on('data', (data) => log.info('[Frontend]', data.toString()));
      this.frontendProcess.stderr?.on('data', (data) => log.error('[Frontend Error]', data.toString()));
      this.frontendProcess.on('exit', (code) => {
        log.warn(`Development frontend exited with code: ${code}`);
        this.frontendProcess = null;
      });
      return;
    }

    this.frontendPort = await this.findAvailablePort(preferredFrontendPort);
    const frontendDir = path.join(process.resourcesPath, 'frontend', 'standalone');
    const serverJs = path.join(frontendDir, 'server.js');
    log.info(`  - frontendDir: ${frontendDir}`);
    log.info(`  - serverJs: ${serverJs}`);
    log.info(`  - serverJs exists: ${fs.existsSync(serverJs)}`);
    log.info(`  - frontendPort: ${this.frontendPort}`);

    if (!fs.existsSync(serverJs)) {
      log.warn(`Frontend server entrypoint not found: ${serverJs}`);
      return;
    }
    log.info('Launching packaged frontend...');
    const backendUrl = this.getBackendBaseUrl();
    const frontendEnv = {
      ...serviceEnv,
      ELECTRON_RUN_AS_NODE: '1',
      NODE_ENV: 'production',
      PORT: String(this.frontendPort),
      HOSTNAME: '127.0.0.1',
      NEXT_PUBLIC_BACKEND_URL: backendUrl,
      NEXT_PUBLIC_API_URL: backendUrl,
      NEXT_PUBLIC_LAOMA_BACKEND_URL: backendUrl,
      LAOMA_BACKEND_URL: backendUrl,
      NEXT_TELEMETRY_DISABLED: '1'
    };
    this.frontendProcess = spawn(process.execPath, [serverJs], {
      env: frontendEnv,
      cwd: frontendDir,
      windowsHide: true
    });
    this.frontendProcess.stdout?.on('data', (data) => log.info('[Frontend]', data.toString()));
    this.frontendProcess.stderr?.on('data', (data) => log.error('[Frontend Error]', data.toString()));
    this.frontendProcess.on('exit', (code) => {
      log.warn(`Packaged frontend exited with code: ${code}`);
    });
  }


  async startBackend(env) {
    if (this.backendProcess) {
      return;
    }
    if (!this.backendPort) {
      await this.prepareManagedServicePorts();
    }
    const backendPort = this.getBackendPort();
    if (await this.isPrismBackendOnPort(backendPort)) {
      log.warn(`Backend already running on port ${backendPort}; skipping start.`);
      return;
    }
    const backendDir = this.getBackendDir();
    const backendExe = this.getServiceExe('backend');
    const pythonPath = this.getPythonPath();
    const mainScript = path.join(backendDir, 'fastapi_app', 'run.py');

    log.info('Starting FastAPI backend...');
    log.info('  - Backend Dir:', backendDir);
    log.info('  - Backend Dir exists:', fs.existsSync(backendDir));
    log.info('  - Backend Exe:', backendExe || 'N/A');
    log.info('  - Python Path:', pythonPath);
    log.info('  - Python exists:', fs.existsSync(pythonPath));
    log.info('  - Main Script:', mainScript);
    log.info('  - Script exists:', fs.existsSync(mainScript));

    return new Promise((resolve, reject) => {
      if (!backendExe && !fs.existsSync(mainScript)) {
        log.error(`FastAPI entry script not found: ${mainScript}`);
        resolve();
        return;
      }

      const launchCmd = backendExe || pythonPath;
      const launchArgs = backendExe ? [] : [mainScript];

      log.info('  - Launch Command:', launchCmd);
      log.info('  - Launch Args:', launchArgs.join(' '));

      this.backendProcess = spawn(launchCmd, launchArgs, {
        cwd: backendDir,
        env: {
          ...env,
          PORT: String(backendPort),
          PYTHONPATH: backendDir
        },
        windowsHide: true
      });

      this.backendProcess.stdout?.on('data', (data) => {
        const output = data.toString();
        log.info('[Backend]', output);
        if (output.includes('Uvicorn running') || output.includes('Application startup complete')) {
          log.info('FastAPI backend started successfully');
          resolve();
        }
      });

      this.backendProcess.stderr?.on('data', (data) => {
        log.error('[Backend Error]', data.toString());
      });

      this.backendProcess.on('error', (error) => {
        log.error('Backend process failed to start:', error);
        reject(error);
      });

      this.backendProcess.on('exit', (code) => {
        log.warn(`Backend process exited with code: ${code}`);
      });

      setTimeout(() => {
        log.warn('Backend startup timed out; continuing app launch');
        resolve();
      }, 10000);
    });
  }

  createLauncherWindow() {
    log.info('Creating launcher window...');

    this.launcherWindow = new BrowserWindow({
      width: 800,
      height: 700,
      resizable: false,
      frame: true,
      backgroundColor: '#0a0a0e',
      titleBarStyle: 'default',
      autoHideMenuBar: true,
      icon: this.appIconPath || undefined,
      webPreferences: {
        preload: path.join(__dirname, '../preload/index.js'),
        contextIsolation: true,
        nodeIntegration: false,
        webSecurity: true
      }
    });

    // 加载启动管理器页面
    const launcherPath = path.join(__dirname, '../launcher/launcher.html');
    log.info('Loading launcher page:', launcherPath);
    this.launcherWindow.loadFile(launcherPath);

    // 窗口关闭事件
    this.launcherWindow.on('closed', () => {
      this.launcherWindow = null;
      log.info('Launcher window closed');
    });

    this.launcherWindow.show();
  }

  createSettingsWindow() {
    log.info('Creating settings window...');

    // 如果设置窗口已存在，直接显示
    if (this.settingsWindow) {
      this.settingsWindow.show();
      this.settingsWindow.focus();
      return;
    }

    this.settingsWindow = new BrowserWindow({
      width: 1200,
      height: 800,
      minWidth: 1000,
      minHeight: 600,
      backgroundColor: '#0a0a0e',
      titleBarStyle: 'default',
      autoHideMenuBar: true,
      icon: this.appIconPath || undefined,
      webPreferences: {
        preload: path.join(__dirname, '../preload/index.js'),
        contextIsolation: true,
        nodeIntegration: false,
        webSecurity: false // 允许访问 localhost API
      }
    });

    // 加载设置页面
    const settingsPath = path.join(__dirname, '../settings/settings.html');
    log.info('Loading settings page:', settingsPath);
    this.settingsWindow.loadFile(settingsPath);

    // 窗口关闭事件
    this.settingsWindow.on('closed', () => {
      this.settingsWindow = null;
      log.info('Settings window closed');
    });

    this.settingsWindow.show();
  }

  createMainWindow() {
    log.info('Creating main window...');

    this.mainWindow = new BrowserWindow({
      width: 1400,
      height: 900,
      minWidth: 1200,
      minHeight: 700,
      show: false,
      backgroundColor: '#0a0a0e',
      titleBarStyle: 'default',
      autoHideMenuBar: true,
      icon: this.appIconPath || undefined,
      webPreferences: {
        preload: path.join(__dirname, '../preload/index.js'),
        contextIsolation: true,
        nodeIntegration: false,
        webSecurity: true,
        webviewTag: true
      }
    });

    const indexPath = path.join(__dirname, '../renderer/index.html');
    log.info('Loading app shell:', indexPath);
    this.mainWindow.loadFile(indexPath);

    this.mainWindow.once('ready-to-show', () => {
      this.mainWindow.show();
      log.info('Main window is ready');
    });

    this.mainWindow.on('close', (event) => {
      if (this.isQuitting) {
        return;
      }

      event.preventDefault();
      this.mainWindow.hide();
      log.info('Main window hidden to tray');
    });

    this.mainWindow.on('closed', () => {
      this.mainWindow = null;
      log.info('Main window closed');
    });
  }

  setupIPC() {
    log.info('Setting up IPC handlers...');

    // ========== C17 客户端 JWT 凭证加密存储(Electron safeStorage) ==========
    //
    // 设计:渲染进程通过 preload 的 `electronAPI.credential.*` 调用:
    //   - encrypt / decrypt  : 供 `cloud-auth.ts` 自行组装 payload(JSON.stringify + base64)
    //   - save / get / delete: 端到端封装,把 JWT payload 存到 userData/credentials.json
    //
    // safeStorage 在 Windows 走 DPAPI,macOS 走 Keychain,失败(如无可用
    // Keychain)时返回 null,前端会回退到 localStorage。
    //
    // 不启动任何服务、不影响既有 IPC。

    const credentialFilePath = () =>
      path.join(app.getPath('userData'), 'cloud-credentials.json');

    const readCredentialFile = () => {
      try {
        const fs = require('fs');
        if (!fs.existsSync(credentialFilePath())) return null;
        const raw = fs.readFileSync(credentialFilePath(), 'utf8');
        return raw;
      } catch (err) {
        log.warn('[credential] read failed:', err?.message || err);
        return null;
      }
    };

    const writeCredentialFile = (payload) => {
      try {
        const fs = require('fs');
        fs.writeFileSync(credentialFilePath(), payload, 'utf8');
        try {
          fs.chmodSync(credentialFilePath(), 0o600);
        } catch {
          // Windows 无 chmod 效果,忽略
        }
        return true;
      } catch (err) {
        log.error('[credential] write failed:', err);
        return false;
      }
    };

    const deleteCredentialFile = () => {
      try {
        const fs = require('fs');
        if (fs.existsSync(credentialFilePath())) fs.unlinkSync(credentialFilePath());
        return true;
      } catch (err) {
        log.warn('[credential] delete failed:', err?.message || err);
        return false;
      }
    };

    ipcMain.handle('credential:isAvailable', () => {
      try {
        return { success: true, available: safeStorage.isSafeStorageAvailable() };
      } catch (error) {
        log.error('safeStorage.isSafeStorageAvailable failed:', error);
        return { success: false, available: false, error: error.message };
      }
    });

    ipcMain.handle('credential:encrypt', (event, plaintext) => {
      try {
        if (typeof plaintext !== 'string') return { success: false, error: 'expected string' };
        const buf = safeStorage.encryptString(plaintext);
        // 以 base64 返回,便于 JSON 序列化
        return { success: true, ciphertext: buf.toString('base64') };
      } catch (error) {
        log.warn('[credential] encrypt failed:', error);
        return { success: false, error: error.message };
      }
    });

    ipcMain.handle('credential:decrypt', (event, ciphertext) => {
      try {
        if (typeof ciphertext !== 'string' || !ciphertext) {
          return { success: false, error: 'expected base64 ciphertext' };
        }
        const buf = Buffer.from(ciphertext, 'base64');
        return { success: true, plaintext: safeStorage.decryptString(buf) };
      } catch (error) {
        log.warn('[credential] decrypt failed:', error);
        return { success: false, error: error.message };
      }
    });

    // 端到端:直接保存 JSON 明文 → 加密 → 落盘。用于简单场景。
    ipcMain.handle('credential:save', (event, plaintext) => {
      try {
        if (typeof plaintext !== 'string') return { success: false, error: 'expected string' };
        if (!safeStorage.isSafeStorageAvailable()) {
          return { success: false, error: 'safeStorage unavailable' };
        }
        const buf = safeStorage.encryptString(plaintext);
        return writeCredentialFile(buf.toString('base64'))
          ? { success: true }
          : { success: false, error: 'write failed' };
      } catch (error) {
        log.error('[credential] save failed:', error);
        return { success: false, error: error.message };
      }
    });

    ipcMain.handle('credential:get', () => {
      try {
        const ciphertext = readCredentialFile();
        if (!ciphertext) return { success: true, plaintext: null };
        if (!safeStorage.isSafeStorageAvailable()) {
          return { success: false, error: 'safeStorage unavailable' };
        }
        const plaintext = safeStorage.decryptString(Buffer.from(ciphertext, 'base64'));
        return { success: true, plaintext };
      } catch (error) {
        log.warn('[credential] get failed:', error);
        return { success: false, error: error.message };
      }
    });

    ipcMain.handle('credential:delete', () => {
      return deleteCredentialFile()
        ? { success: true }
        : { success: false, error: 'delete failed' };
    });

    // 获取 Playwright 浏览器路径
    ipcMain.handle('automation:getBrowserPath', () => {
      return this.automationBrowserPath;
    });

    // 创建可视化浏览器窗口（用于调试和预览）
    ipcMain.handle('browser:createVisual', async (event, url, options = {}) => {
      log.info('Creating visual browser window:', url);

      const browserWindow = new BrowserWindow({
        width: options.width || 1200,
        height: options.height || 800,
        show: true,
        backgroundColor: '#0a0a0e',
        icon: this.appIconPath || undefined,
        title: options.title || 'Browser Preview',
        webPreferences: {
          contextIsolation: true,
          nodeIntegration: false,
          webSecurity: true
        }
      });

      await browserWindow.loadURL(url);

      const windowId = browserWindow.id;
      this.visualBrowserWindows.set(windowId, browserWindow);

      browserWindow.on('closed', () => {
        this.visualBrowserWindows.delete(windowId);
      });

      return windowId;
    });

    // 关闭可视化浏览器窗口
    ipcMain.handle('browser:closeVisual', (event, windowId) => {
      const win = this.visualBrowserWindows.get(windowId);
      if (win && !win.isDestroyed()) {
        win.close();
        return true;
      }
      return false;
    });

    // 获取应用信息
    ipcMain.handle('app:getInfo', () => {
      return {
        version: app.getVersion(),
        name: app.getName(),
        isPackaged: this.isPackagedRuntime,
        runtimeMode: this.isPackagedRuntime ? 'packaged' : 'development',
        resourcesPath: process.resourcesPath,
        automationBrowserPath: this.automationBrowserPath,
        runtimeSettings: this.runtimeSettings,
        browserRuntimeInfo: this.getBrowserRuntimeInfo(),
        backendUrl: this.getBackendBaseUrl(),
        backendPort: this.getBackendPort(),
        frontendUrl: this.getFrontendBaseUrl(),
        frontendPort: this.getFrontendPort(),
        systemApiBaseUrl: this.getSystemApiBaseUrl(),
        versionInfo: this.getVersionInfo(),
        supervisorApiPort: this.getSupervisorApiPort()
      };
    });

    // 失败根因上报：supervisor 诊断
    ipcMain.handle('supervisor:get-diagnostics', async () => {
      return {
        success: true,
        diagnostics: await this.getSupervisorDiagnostics(5000),
        supervisorExit: this.lastSupervisorExit || null,
        supervisorApiPort: this.getSupervisorApiPort()
      };
    });

    ipcMain.handle('settings:get', () => {
      return this.runtimeSettings;
    });

    ipcMain.handle('settings:update', (event, settings = {}) => {
      try {
        if (settings.automationRuntime === 'patchright') {
          const runtimeInfo = this.getBrowserRuntimeInfo();
          const selectedRuntime = runtimeInfo.runtimes[settings.automationRuntime];
          if (!selectedRuntime?.installed || selectedRuntime.driverInstalled === false) {
            return {
              success: false,
              error: `runtime_incomplete:${settings.automationRuntime}`,
              browserRuntimeInfo: runtimeInfo
            };
          }
        }
        const nextSettings = this.saveRuntimeSettings(settings);
        return {
          success: true,
          settings: nextSettings,
          browserRuntimeInfo: this.getBrowserRuntimeInfo()
        };
      } catch (error) {
        log.error('Failed to update runtime settings:', error);
        return { success: false, error: error.message };
      }
    });

    ipcMain.handle('browserRuntime:getStatus', () => {
      try {
        return { success: true, browserRuntimeInfo: this.getBrowserRuntimeInfo() };
      } catch (error) {
        log.error('Failed to inspect browser runtime info:', error);
        return { success: false, error: error.message };
      }
    });

    ipcMain.handle('browserRuntime:install', async (event, target) => {
      try {
        return await this.installBrowserComponent(target);
      } catch (error) {
        log.error(`Failed to install browser runtime target ${target}:`, error);
        return { success: false, error: error.message };
      }
    });

    ipcMain.handle('browserRuntime:uninstall', async (event, target) => {
      try {
        return await this.uninstallBrowserComponent(target);
      } catch (error) {
        log.error(`Failed to uninstall browser runtime target ${target}:`, error);
        return { success: false, error: error.message };
      }
    });

    // 设置 Session Cookies
    ipcMain.handle('session:setCookies', async (event, partition, cookies) => {
      log.info(`Setting ${cookies.length} cookies for partition ${partition}`);
      const { session } = require('electron');
      const sess = session.fromPartition(partition);

      const sameSiteMap = {
        None: 'no_restriction',
        Lax: 'lax',
        Strict: 'strict',
        no_restriction: 'no_restriction',
        lax: 'lax',
        strict: 'strict'
      };
      const results = [];

      for (const cookie of cookies) {
        try {
          if (!cookie?.name || !cookie?.domain) {
            throw new Error('Missing cookie name or domain');
          }
          const pathName = cookie.path || '/';
          const hostname = cookie.domain.startsWith('.') ? cookie.domain.substring(1) : cookie.domain;
          const details = {
            url: `${cookie.secure ? 'https' : 'http'}://${hostname}${pathName}`,
            name: cookie.name,
            value: String(cookie.value ?? ''),
            path: pathName,
            secure: Boolean(cookie.secure),
            httpOnly: Boolean(cookie.httpOnly)
          };
          if (!cookie.name.startsWith('__Host-')) {
            details.domain = cookie.domain;
          }
          if (typeof cookie.expires === 'number' && cookie.expires > 0) {
            details.expirationDate = cookie.expires;
          }
          if (cookie.sameSite && sameSiteMap[cookie.sameSite]) {
            details.sameSite = sameSiteMap[cookie.sameSite];
          }
          await sess.cookies.set(details);
          results.push({ name: cookie.name, domain: cookie.domain, success: true });
        } catch (error) {
          log.error(`Failed to set cookie ${cookie?.name || '<unknown>'}:`, error);
          results.push({ name: cookie?.name, domain: cookie?.domain, success: false, error: error.message });
        }
      }

      const failed = results.filter((item) => !item.success);
      try {
        await sess.cookies.flushStore();
      } catch (error) {
        log.warn(`Cookie flush failed for partition ${partition}:`, error);
      }
      log.info(`Cookie setup finished for ${partition}: ${results.length - failed.length}/${results.length}`);
      return { success: failed.length === 0, results };
    });

    // ========== 绯荤粺绠＄悊 IPC 澶勭悊鍣?==========

    ipcMain.handle('system:quit-app', async () => {
      return this.quitApplication();
    });

    // 鑾峰彇绯荤粺鐘舵€?
    ipcMain.handle('system:get-status', () => {
      return {
        frontend: {
          running: this.frontendProcess !== null && !this.frontendProcess.killed,
          pid: this.frontendProcess?.pid
        },
        backend: {
          running: this.backendProcess !== null && !this.backendProcess.killed,
          pid: this.backendProcess?.pid
        },
        supervisor: {
          running: this.supervisorProcess !== null && !this.supervisorProcess.killed,
          pid: this.supervisorProcess?.pid
        },
        automation_worker: {
          running: this.automationWorkerProcess !== null && !this.automationWorkerProcess.killed,
          pid: this.automationWorkerProcess?.pid
        },
        celery_worker: {
          running: this.celeryProcess !== null && !this.celeryProcess.killed,
          pid: this.celeryProcess?.pid
        },
        hermes_gateway: {
          running: false,
          pid: null,
        },
        hermes_dashboard: {
          running: false,
          pid: null,
        },
        hermes_webui: {
          running: false,
          pid: null,
        }
      };
    });

    // ========== Supervisor 绠＄悊 IPC (閫氳繃 HTTP API 涓?supervisor 閫氫俊) ==========

    // 鑾峰彇 supervisor 绠＄悊鐨勬湇鍔＄姸鎬?
    ipcMain.handle('supervisor:get-status', async () => {
      try {
        if (!this.supervisorProcess || this.supervisorProcess.killed) {
          return {
            frontend: {
              running: this.frontendProcess !== null && !this.frontendProcess.killed,
              pid: this.frontendProcess?.pid
            },
            backend: {
              running: this.backendProcess !== null && !this.backendProcess.killed,
              pid: this.backendProcess?.pid
            },
            supervisor: {
              running: this.supervisorProcess !== null && !this.supervisorProcess.killed,
              pid: this.supervisorProcess?.pid
            },
            automation_worker: {
              running: this.automationWorkerProcess !== null && !this.automationWorkerProcess.killed,
              pid: this.automationWorkerProcess?.pid
            },
            celery_worker: {
              running: this.celeryProcess !== null && !this.celeryProcess.killed,
              pid: this.celeryProcess?.pid
            },
            hermes_gateway: {
              running: false,
              pid: null,
            },
            hermes_dashboard: {
              running: false,
              pid: null,
            },
            hermes_webui: {
              running: false,
              pid: null,
            }
          };
        }

        const result = await this.getSupervisorStatus(5000);
        const payload = result?.data || {};
        payload.frontend = {
          running: this.frontendProcess !== null && !this.frontendProcess.killed,
          pid: this.frontendProcess?.pid
        };
        const workerStatus = payload.automation_worker || payload.worker || { running: false, pid: null, external: false };
        const celeryStatus = payload.celery_worker || payload.celery || { running: false, pid: null, external: false };
        const gatewayStatus = payload.hermes_gateway || payload.gateway || { running: false, pid: null, external: false };
        const hermesDashboardStatus = payload.hermes_dashboard || payload.dashboard || { running: false, pid: null, external: false };
        const hermesWebuiStatus = payload.hermes_webui || payload.webui || { running: false, pid: null, external: false };
        return {
          backend: payload.backend || { running: false, pid: null, external: false },
          automation_worker: workerStatus,
          celery_worker: celeryStatus,
          hermes_gateway: gatewayStatus,
          hermes_dashboard: hermesDashboardStatus,
          hermes_webui: hermesWebuiStatus,
          frontend: payload.frontend,
          supervisor: {
            running: this.supervisorProcess !== null && !this.supervisorProcess.killed,
            pid: this.supervisorProcess?.pid
          }
        };
      } catch (error) {
        log.error('Failed to get supervisor status:', error);
        throw error;
      }
    });

    // 启动所有服务
    ipcMain.handle('supervisor:start-all', async () => {
      try {
        const http = require('http');

        return new Promise((resolve, reject) => {
          const req = http.request({
            hostname: '127.0.0.1',
            port: this.getSupervisorApiPort(),
            path: '/api/start',
            method: 'POST'
          }, (res) => {
            let data = '';

            res.on('data', (chunk) => {
              data += chunk;
            });

            res.on('end', () => {
              try {
                const result = JSON.parse(data);
                // 同时启动前端
                this.startFrontend();
                resolve({ success: true, message: result.message });
              } catch (error) {
                reject(error);
              }
            });
          });

          req.on('error', (error) => {
            reject(error);
          });

          req.end();
        });
      } catch (error) {
        log.error('Failed to start supervisor-managed services:', error);
        return { success: false, error: error.message };
      }
    });

    // 停止所有服务


    // 启动主应用
    ipcMain.handle('supervisor:launch-main-app', async () => {
      try {
        // 关闭启动管理器窗口
        if (this.launcherWindow) {
          this.launcherWindow.close();
          this.launcherWindow = null;
        }

        // 鍒涘缓涓荤獥鍙?
        if (!this.mainWindow) {
          this.createMainWindow();
        }

        return { success: true };
      } catch (error) {
        log.error('Failed to launch main application window:', error);
        return { success: false, error: error.message };
      }
    });

    // ========== 打开设置窗口 ==========
    ipcMain.handle('window:openSettings', () => {
      log.info('Opening settings window');
      this.createSettingsWindow();
      return { success: true };
    });

    // ========== 数据清理 IPC ==========
    ipcMain.handle('system:clear-video-data', async (event, options = {}) => {
      log.info('Clearing video data...');
      try {
        const http = require('http');
        const backendBaseUrl = new URL(this.getBackendBaseUrl());
        const backendPort = Number.parseInt(backendBaseUrl.port, 10) || (backendBaseUrl.protocol === 'https:' ? 443 : 80);

        return new Promise((resolve, reject) => {
          const req = http.request({
            hostname: backendBaseUrl.hostname,
            port: backendPort,
            path: '/api/v1/system/clear-video-data',
            method: 'POST'
          }, (res) => {
            let data = '';

            res.on('data', (chunk) => {
              data += chunk;
            });

            res.on('end', () => {
              try {
                const result = JSON.parse(data);
                if (res.statusCode === 200) {
                  log.info('Video data cleared successfully');
                  resolve(result);
                } else {
                  log.error('Video data clear failed:', result);
                  reject(new Error(result.detail || 'Clear operation failed'));
                }
              } catch (error) {
                log.error('Failed to parse clear-video-data response:', error);
                reject(error);
              }
            });
          });

          req.on('error', (error) => {
            log.error('clear-video-data request failed:', error);
            reject(error);
          });

          req.setTimeout(30000, () => {
            req.destroy();
            reject(new Error('Request timeout'));
          });

          req.end();
        });
      } catch (error) {
        log.error('Failed to clear video data:', error);
        return { success: false, error: error.message };
      }
    });

    log.info('IPC handlers ready');
  }

  setupAppEvents() {
    app.on('second-instance', () => {
      log.info('Detected second instance, focusing current window');
      this.showMainWindow();
    });

    app.on('window-all-closed', () => {
      log.info('All windows closed; application remains available from tray');
    });

    app.on('activate', () => {
      this.showMainWindow();
    });

    app.on('before-quit', () => {
      this.isQuitting = true;
      log.info('Application is about to quit, cleaning up resources...');
      stopUpdateManager();
      this.cleanup();
      if (this.tray) {
        this.tray.destroy();
        this.tray = null;
      }
    });
  }

  cleanup() {
    log.info('Cleaning up resources...');

    for (const [, win] of this.visualBrowserWindows) {
      if (!win.isDestroyed()) {
        win.close();
      }
    }
    this.visualBrowserWindows.clear();

    const stopProcess = (proc, label) => {
      if (!proc) {
        return;
      }

      try {
        log.info(`Stopping ${label} process...`);
        if (process.platform === 'win32' && proc.pid) {
          execSync(`taskkill /F /T /PID ${proc.pid}`, { stdio: 'ignore' });
        } else if (!proc.killed) {
          proc.kill();
        }
      } catch (error) {
        log.warn(`Failed to terminate ${label}:`, error);
      }
    };

    stopProcess(this.frontendProcess, 'frontend');
    this.frontendProcess = null;

    stopProcess(this.celeryProcess, 'celery');
    this.celeryProcess = null;

    stopProcess(this.automationWorkerProcess, 'automation worker');
    this.automationWorkerProcess = null;

    stopProcess(this.backendProcess, 'backend');
    this.backendProcess = null;

    stopProcess(this.redisProcess, 'redis');
    this.redisProcess = null;

    stopProcess(this.supervisorProcess, 'supervisor');
    this.supervisorProcess = null;

    // 兜底：按名称杀掉所有可能残留的子进程（PID 失效或不在进程树里）
    if (process.platform === 'win32') {
      const residualNames = [
        'backend.exe',
        'automation-worker.exe',
        'celery-worker.exe',
        'redis-server.exe',
        'supervisor.exe'
      ];
      for (const name of residualNames) {
        try {
          execSync(`taskkill /F /T /IM ${name} 2>NUL`, { stdio: 'ignore' });
          log.info(`Terminated residual ${name}`);
        } catch (e) {
          // 进程不存在，忽略
        }
      }
    }

    this.servicesStarted = false;
    log.info('Resource cleanup complete');
  }
}

// 启动应用
const prismApp = new PrismApp();

// 捕获未处理的错误
// 最后兜底：进程退出时确保所有子进程被清理（防止 before-quit 未触发时残留）
process.on('exit', () => {
  try {
    prismApp.cleanup();
  } catch (e) {
    // 忽略退出时的清理错误
  }
});

process.on('uncaughtException', (error) => {
  log.error('Uncaught exception:', error);
});

process.on('unhandledRejection', (reason, promise) => {
  log.error('Unhandled promise rejection:', reason);
});

// 初始化应用
prismApp.initialize().catch((error) => {
  log.error('Application initialization failed:', error);
  if (app && app.quit) {
    app.quit();
  } else {
    process.exit(1);
  }
});
