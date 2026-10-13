/**
 * C19 客户端云端认证 / 订阅客户端封装。
 *
 * 与 `env.ts` 中的 `API_ENDPOINTS.cloud*` 端点配对,面向浏览器渲染进程;
 * Electron 环境若挂了 `window.electronAPI.credential`,token 会通过
 * `safeStorage` 加密后落盘(见 `desktop-electron/src/main/index.js` 的
 * `credential:save`)。
 *
 * 设计约束(与设计文档 §4.3 对齐):
 *   - 单页应用内保持一个 `Promise` 单例,避免并发刷新导致多个 refresh 请求。
 *   - localStorage 作为兜底存储(非 Electron / safeStorage 不可用时);
 *     Electron + safeStorage 时优先走加密存储。
 *   - token 字段只在内存 & 加密 blob 中出现,不打印日志。
 */

import { API_ENDPOINTS } from "./env"

export interface CloudUser {
  id: number
  username: string
  email?: string | null
  is_active: boolean
  created_at?: string | null
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: "bearer"
  expires_in: number
  /** 客户端本地记录,单位秒(与 expires_in 配对) */
  obtained_at: number
}

export interface SubscriptionStatus {
  valid: boolean
  reason: string
  plan: string
  status: string
  expire_at: string | null
  quota: number
  used: number
  remaining: number
  is_pro: boolean
  /** 客户端本地补的字段,来自 verify 成功 */
  checked_at?: number
}

/** 心跳间隔:24 小时(设计文档 §4.3) */
export const LICENSE_HEARTBEAT_INTERVAL_MS = 24 * 60 * 60 * 1000
/** 登录后立即校验一次(避免长时间空闲) */
export const LICENSE_INITIAL_TIMEOUT_MS = 0

const ACCESS_TOKEN_KEY = "prism_cloud_access_token"
const REFRESH_TOKEN_KEY = "prism_cloud_refresh_token"
const OBTAINED_AT_KEY = "prism_cloud_obtained_at"
const EXPIRES_IN_KEY = "prism_cloud_expires_in"
const USER_KEY = "prism_cloud_user"

const STORAGE_PREFIX = "prism_cloud_"

/** 判断是否运行在 Electron + 已暴露 credential IPC。 */
function hasSafeStorage(): boolean {
  return (
    typeof window !== "undefined" &&
    Boolean((window as any).electronAPI?.credential?.encrypt)
  )
}

async function safeStorageEncrypt(plaintext: string): Promise<string | null> {
  const api = (window as any).electronAPI?.credential
  if (!api?.encrypt) return null
  try {
    const out = await api.encrypt(plaintext)
    return typeof out === "string" && out.length > 0 ? out : null
  } catch {
    return null
  }
}

async function safeStorageDecrypt(ciphertext: string): Promise<string | null> {
  const api = (window as any).electronAPI?.credential
  if (!api?.decrypt) return null
  try {
    const out = await api.decrypt(ciphertext)
    return typeof out === "string" && out.length > 0 ? out : null
  } catch {
    return null
  }
}

async function safeStorageDeleteAll(): Promise<void> {
  const api = (window as any).electronAPI?.credential
  if (!api?.delete) return
  try {
    await api.delete()
  } catch {
    /* 忽略:主进程可能已销毁 */
  }
}

/**
 * 存储:Electron 走 safeStorage 加密 blob;否则走 localStorage(仅用于
 * 浏览器/开发环境,明文兜底但受同源约束)。
 */
async function persistToken(pair: TokenPair, user?: CloudUser | null): Promise<void> {
  const payload = JSON.stringify({
    ...pair,
    user: user ?? (await readUser()),
    ts: Date.now(),
  })
  if (hasSafeStorage()) {
    const blob = await safeStorageEncrypt(payload)
    if (blob !== null) return
  }
  // 明文兜底:分字段写,便于调试 & 兼容
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(ACCESS_TOKEN_KEY, pair.access_token)
    window.localStorage.setItem(REFRESH_TOKEN_KEY, pair.refresh_token)
    window.localStorage.setItem(OBTAINED_AT_KEY, String(pair.obtained_at))
    window.localStorage.setItem(EXPIRES_IN_KEY, String(pair.expires_in))
    if (user !== undefined) {
      if (user) window.localStorage.setItem(USER_KEY, JSON.stringify(user))
      else window.localStorage.removeItem(USER_KEY)
    }
  } catch {
    /* storage 满或隐私模式,忽略 */
  }
}

async function readPayload(): Promise<{
  access_token: string
  refresh_token: string
  obtained_at: number
  expires_in: number
  user?: CloudUser | null
} | null> {
  if (hasSafeStorage()) {
    const api = (window as any).electronAPI?.credential
    try {
      const blob = await api.get?.()
      if (typeof blob === "string" && blob.length > 0) {
        const decrypted = await safeStorageDecrypt(blob)
        if (decrypted) return JSON.parse(decrypted)
      }
    } catch {
      /* 忽略,回退 localStorage */
    }
  }
  if (typeof window === "undefined") return null
  const at = window.localStorage.getItem(ACCESS_TOKEN_KEY)
  if (!at) return null
  return {
    access_token: at,
    refresh_token: window.localStorage.getItem(REFRESH_TOKEN_KEY) ?? "",
    obtained_at: Number(window.localStorage.getItem(OBTAINED_AT_KEY) ?? 0),
    expires_in: Number(window.localStorage.getItem(EXPIRES_IN_KEY) ?? 0),
    user: (await readUser()) ?? null,
  }
}

async function readUser(): Promise<CloudUser | null> {
  if (typeof window === "undefined") return null
  const raw = window.localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    return JSON.parse(raw) as CloudUser
  } catch {
    return null
  }
}

async function clearAllStorage(): Promise<void> {
  await safeStorageDeleteAll()
  if (typeof window === "undefined") return
  for (const key of [
    ACCESS_TOKEN_KEY,
    REFRESH_TOKEN_KEY,
    OBTAINED_AT_KEY,
    EXPIRES_IN_KEY,
    USER_KEY,
  ]) {
    try {
      window.localStorage.removeItem(key)
    } catch {
      /* 忽略 */
    }
  }
}

/** 剩余有效期(秒)。0 表示已过期。 */
function remainingSeconds(pair: Pick<TokenPair, "obtained_at" | "expires_in">): number {
  const now = Date.now() / 1000
  return Math.max(0, Math.round(pair.obtained_at + pair.expires_in - now))
}

/** 触发 refresh 前的宽裕度(秒) */
const REFRESH_LEEWAY_SECONDS = 60

async function requestJson<T>(
  method: "GET" | "POST",
  url: string,
  init?: {
    headers?: Record<string, string>;
    token?: string;
    body?: unknown;
  },
): Promise<{ ok: boolean; status: number; data: T; detail?: string }> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(init?.headers as Record<string, string>),
  }
  if (init?.token) headers["Authorization"] = `Bearer ${init.token}`
  const opts: RequestInit = {
    method,
    headers,
    credentials: "omit",
    body: init?.body ? JSON.stringify(init.body) : undefined,
  }
  let resp: Response
  try {
    resp = await fetch(url, opts)
  } catch (e) {
    throw new CloudAuthError("cloud unreachable", "network")
  }
  let data: any = {}
  try {
    data = await resp.json()
  } catch {
    data = {}
  }
  return {
    ok: resp.ok,
    status: resp.status,
    data: data as T,
    detail: (data && typeof data.detail === "string" && data.detail) || undefined,
  }
}

export class CloudAuthError extends Error {
  constructor(
    message: string,
    public code: "network" | "unauthorized" | "expired" | "invalid" | "server" | "client" = "server",
    public status?: number,
  ) {
    super(message)
    this.name = "CloudAuthError"
  }
}

/** 内部使用:清理所有存储(供 `me()` 401 时调用) */
async function logout(): Promise<void> {
  await clearAllStorage()
}

type LoginBody = { username: string; password: string }
type RegisterBody = { username: string; email: string; password: string }

let _refreshInflight: Promise<TokenPair | null> | null = null

async function refreshAccessToken(pair: {
  refresh_token: string
  obtained_at: number
  expires_in: number
}): Promise<TokenPair | null> {
  if (!pair.refresh_token) return null
  const r = await requestJson<{ access_token: string; expires_in: number; token_type?: string }>(
    "POST",
    API_ENDPOINTS.cloudAuthRefresh,
    { body: { refresh_token: pair.refresh_token } },
  )
  if (!r.ok || !r.data.access_token) return null
  const next: TokenPair = {
    access_token: r.data.access_token,
    refresh_token: pair.refresh_token,
    token_type: (r.data.token_type as "bearer") ?? "bearer",
    expires_in: r.data.expires_in,
    obtained_at: Date.now() / 1000,
  }
  await persistToken(next)
  return next
}

async function ensureAccessToken(pair: TokenPair): Promise<string> {
  if (!pair.access_token) return ""
  if (remainingSeconds(pair) <= REFRESH_LEEWAY_SECONDS) {
    if (!_refreshInflight) {
      _refreshInflight = refreshAccessToken(pair).finally(() => {
        _refreshInflight = null
      })
    }
    const refreshed = await _refreshInflight
    if (!refreshed) return ""
    return refreshed.access_token
  }
  return pair.access_token
}

export const cloudAuth = {
  async login(body: LoginBody): Promise<TokenPair> {
    const r = await requestJson<TokenPair & { token_type?: string }>(
      "POST",
      API_ENDPOINTS.cloudAuthLogin,
      { body },
    )
    if (!r.ok) {
      const code = r.status === 401 ? "unauthorized" : r.status >= 500 ? "server" : "client"
      throw new CloudAuthError(r.detail || `login failed (HTTP ${r.status})`, code, r.status)
    }
    const pair: TokenPair = {
      access_token: r.data.access_token,
      refresh_token: r.data.refresh_token,
      token_type: (r.data.token_type as "bearer") ?? "bearer",
      expires_in: r.data.expires_in,
      obtained_at: Date.now() / 1000,
    }
    await persistToken(pair)
    return pair
  },

  async register(body: RegisterBody): Promise<CloudUser> {
    const r = await requestJson<CloudUser>(
      "POST",
      API_ENDPOINTS.cloudAuthRegister,
      { body },
    )
    if (!r.ok) {
      const code = r.status === 409 ? "client" : r.status >= 500 ? "server" : "client"
      throw new CloudAuthError(r.detail || `register failed (HTTP ${r.status})`, code, r.status)
    }
    return r.data
  },

  async me(): Promise<CloudUser | null> {
    const payload = await readPayload()
    if (!payload) return null
    const token = await ensureAccessToken({
      access_token: payload.access_token,
      refresh_token: payload.refresh_token,
      obtained_at: payload.obtained_at,
      expires_in: payload.expires_in,
    } as TokenPair)
    if (!token) return null
    const r = await requestJson<CloudUser>("GET", API_ENDPOINTS.cloudAuthMe, { token })
    if (!r.ok) {
      // 401/403 → 清 token
      if (r.status === 401 || r.status === 403) await logout()
      return null
    }
    await persistToken({
      access_token: payload.access_token,
      refresh_token: payload.refresh_token,
      token_type: "bearer",
      expires_in: payload.expires_in,
      obtained_at: payload.obtained_at,
    })
    return r.data
  },

  async getCurrentTokenPair(): Promise<TokenPair | null> {
    const payload = await readPayload()
    if (!payload || !payload.access_token) return null
    return {
      access_token: payload.access_token,
      refresh_token: payload.refresh_token,
      token_type: "bearer",
      expires_in: payload.expires_in,
      obtained_at: payload.obtained_at,
    }
  },

  async getAccessToken(): Promise<string> {
    const payload = await readPayload()
    if (!payload) return ""
    return ensureAccessToken({
      access_token: payload.access_token,
      refresh_token: payload.refresh_token,
      token_type: "bearer",
      expires_in: payload.expires_in,
      obtained_at: payload.obtained_at,
    } as TokenPair)
  },

  /** 检查是否已登录(仅本地 token 存在即视为已登录;不触发网络) */
  isLoggedinLocal(): boolean {
    if (typeof window === "undefined") return false
    // Electron 场景无法读 blob,退回"有 localStorage 也 OK"或让上层用 verify
    const at = window.localStorage.getItem(ACCESS_TOKEN_KEY)
    return Boolean(at)
  },

  async logout(): Promise<void> {
    await clearAllStorage()
  },

  async getSubscription(): Promise<SubscriptionStatus | null> {
    const token = await this.getAccessToken()
    if (!token) return null
    const r = await requestJson<SubscriptionStatus>(
      "GET",
      API_ENDPOINTS.cloudSubscription,
      { token },
    )
    if (!r.ok) return null
    return { ...r.data, checked_at: Date.now() }
  },

  /**
   * 调用 `POST /cloud/license/verify`。
   * 与 gateway 的 `_LICENSE_CACHE_TTL=300s` 不同,这里是**心跳**,返回当前状态。
   */
  async verifyLicense(): Promise<SubscriptionStatus> {
    const token = await this.getAccessToken()
    if (!token) {
      return {
        valid: false,
        reason: "unauthenticated",
        plan: "",
        status: "",
        expire_at: null,
        quota: 0,
        used: 0,
        remaining: 0,
        is_pro: false,
        checked_at: Date.now(),
      }
    }
    const r = await requestJson<SubscriptionStatus>(
      "POST",
      API_ENDPOINTS.cloudLicenseVerify,
      { token, body: {} },
    )
    if (r.status === 401) {
      // token 失效 → 清本地
      await this.logout()
      return {
        valid: false,
        reason: "unauthenticated",
        plan: "",
        status: "",
        expire_at: null,
        quota: 0,
        used: 0,
        remaining: 0,
        is_pro: false,
        checked_at: Date.now(),
      }
    }
    if (!r.ok) {
      return {
        valid: false,
        reason: r.status >= 500 ? "cloud_unreachable" : (r.detail || "license_check_failed"),
        plan: "",
        status: "",
        expire_at: null,
        quota: 0,
        used: 0,
        remaining: 0,
        is_pro: false,
        checked_at: Date.now(),
      }
    }
    return { ...r.data, checked_at: Date.now() }
  },
}

/** 供 `useLicenseHeartbeat` 使用:内部工具,不对外 */
export const _internal = {
  persistToken,
  readPayload,
  clearAllStorage,
  hasSafeStorage,
  remainingSeconds,
}
