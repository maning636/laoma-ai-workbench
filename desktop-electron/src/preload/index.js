const { contextBridge, ipcRenderer } = require('electron');

const invoke = (channel, ...args) => ipcRenderer.invoke(channel, ...args);

// 暴露安全的 API 给渲染进程
contextBridge.exposeInMainWorld('electronAPI', {
  // 浏览器自动化运行时
  automation: {
    getBrowserPath: () => invoke('automation:getBrowserPath')
  },

  // 浏览器窗口管理
  browser: {
    createVisual: (url, options) => invoke('browser:createVisual', url, options),
    closeVisual: (windowId) => invoke('browser:closeVisual', windowId)
  },

  // 会话管理
  session: {
    setCookies: (partition, cookies) => invoke('session:setCookies', partition, cookies)
  },

  // 应用信息
  app: {
    getInfo: () => invoke('app:getInfo')
  },

  settings: {
    get: () => invoke('settings:get'),
    update: (settings) => invoke('settings:update', settings)
  },

  browserRuntime: {
    getStatus: () => invoke('browserRuntime:getStatus'),
    install: (target) => invoke('browserRuntime:install', target),
    uninstall: (target) => invoke('browserRuntime:uninstall', target)
  },

  // 系统管理
  system: {
    quitApp: () => invoke('system:quit-app'),
    getStatus: () => invoke('system:get-status'),
    clearVideoData: (options) => invoke('system:clear-video-data', options)
  },

  // Supervisor 管理（用于启动管理器）
  supervisor: {
    getStatus: () => invoke('supervisor:get-status'),
    startAll: () => invoke('supervisor:start-all'),
    launchMainApp: () => invoke('supervisor:launch-main-app'),
    getDiagnostics: () => invoke('supervisor:get-diagnostics')
  },

  // 自托管更新（electron-updater generic feed）
  updates: {
    getStatus: () => invoke('updates:status'),
    check: () => invoke('updates:check'),
    download: () => invoke('updates:download'),
    install: () => invoke('updates:install'),
    skip: (version) => invoke('updates:skip', version),
    listVersions: () => invoke('updates:list-versions'),
    installVersion: (version) => invoke('updates:install-version', version),
    onStatusChanged: (callback) => {
      const listener = (_event, status) => callback(status);
      ipcRenderer.on('updates:status-changed', listener);
      return () => ipcRenderer.removeListener('updates:status-changed', listener);
    }
  },

  // 凭证加密存储(云端 JWT 走 Electron safeStorage)
  credential: {
    isAvailable: () => invoke('credential:isAvailable'),
    encrypt: async (plaintext) => {
      const r = await invoke('credential:encrypt', plaintext);
      return r && r.success ? r.ciphertext : null;
    },
    decrypt: async (ciphertext) => {
      const r = await invoke('credential:decrypt', ciphertext);
      return r && r.success ? r.plaintext : null;
    },
    save: async (plaintext) => {
      const r = await invoke('credential:save', plaintext);
      return r;
    },
    get: async () => {
      const r = await invoke('credential:get');
      return r && r.success ? (r.plaintext || null) : null;
    },
    delete: () => invoke('credential:delete')
  },

  // 窗口管理
  window: {
    openSettings: () => invoke('window:openSettings')
  }
});

// 日志输出（开发模式）
console.log('🔧 Preload script loaded');
