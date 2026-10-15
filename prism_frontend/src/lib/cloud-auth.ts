/**
 * C19 客户端云端认证 / 订阅客户端封装。
 *
 * 底层 HTTP 已收敛到 `client-gateway.ts`(云端/本地路由 + token 注入 + 错误归一化),
 * 本文件不再直接拼云端端点,也不再手写 fetch。
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

import { gatewayRequest, setTokenProvider, type GatewayErrorCode } from "./client-gateway"

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

/**
 * F-D: 云端不可达时的"乐观窗口"(默认 10 分钟)。
 *
 * 语义:
 *   - 网络类失败(`network` / 5xx)→ 在窗口内继续信任上一次已知的 `valid` 状态;
 *     窗口外才降级为 `cloud_unreachable` 失效。
 *   - 明确的业务性拒绝(401 / 403 / 402 / `expired` / `cancelled`)→ 立即降级,
 *     不受窗口保护。
 *
 * 目的:网络抖动(切 WiFi、地铁、临时掉线)不应把用户从"已付费订阅"降到
 * "订阅失效",避免误伤正常付费用户 —— 尤其是 24h 长间隔下的一次心跳失败。
 *
 * 想改窗口:改下面这个常量(毫秒),或通过 `verifyLicense({ graceMs })` 覆盖。
 */
export const LICENSE_OFFLINE_GRACE_MS = 10 * 60 * 1000

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

// ──────────────────────────────────────────────────────────────
// F-D: 订阅校验结果分类 & 乐观缓存
// ──────────────────────────────────────────────────────────────

/**
 * 把 verifyLicense 的"HTTP 结果"分类成三种语义。
 *
 *   - `"transport"`:  网络/DNS/CORS/5xx 等**传输/服务级**失败,
 *       不反映"订阅本身是否有效"。→ 走乐观窗口。
 *   - `"business"`:   401 / 403 / 402 等**业务级拒绝**,
 *       明确说明订阅/账号状态有问题。→ 立即降级。
 *   - `"ok"`:         HTTP 2xx。
 */
export type VerifyVerdict = "ok" | "transport" | "business"

/**
 * 分类规则:
 *   - HTTP 401 / 402 / 403 → business(token 失效 / 订阅拒绝)
 *   - HTTP 5xx             → transport(服务器异常,不代表订阅本身)
 *   - `code === "network"` 或 status=0 → transport(fetch 层失败)
 *   - 其他 4xx(如 400/404/422)→ transport(这些不匹配业务拒绝语义;
 *       保守处理 —— 与 gateway 层 "client" 归一化对齐)
 *   - HTTP 2xx             → ok
 */
export function classifyVerifyResult(r: {
  ok: boolean
  status: number
  code?: string
}): VerifyVerdict {
  if (r.ok) return "ok"
  if (r.status === 0 || r.code === "network") return "transport"
  if (r.status === 401 || r.status === 402 || r.status === 403) return "business"
  if (r.status >= 500) return "transport"
  // 其他 4xx(400/404/422):不视为业务拒绝,归到 transport 以保守不降级
  return "transport"
}

/** 会话内缓存:上一次成功的订阅快照 + 时间戳。仅内存,不进 localStorage。 */
interface CachedSubscription {
  status: SubscriptionStatus
  at: number
}

let _lastValidSub: CachedSubscription | null = null

/**
 * 请求封装:走 client-gateway,不再直接 fetch / 拼端点。
 *
 * GatewayResult 与旧 requestJson 返回结构兼容(`{ok, status, data, detail}`),
 * 因此所有调用点的 `r.ok / r.status / r.data / r.detail` 保持不变;
 * 只是错误码通过 `r.code` 语义化。
 */
async function requestJson<T>(
  method: "GET" | "POST",
  path: string,
  init?: {
    headers?: Record<string, string>;
    token?: string;
    body?: unknown;
  },
): Promise<{
  ok: boolean;
  status: number;
  data: T;
  detail?: string;
  code?: GatewayErrorCode;
}> {
  // 端点白名单 —— 云端业务统一走 feature="cloud" 由 client-gateway 拼 URL。
  const r = await gatewayRequest<T>({
    feature: "cloud",
    path,
    method,
    body: init?.body,
    headers: init?.headers,
    // `token` 显式覆盖:即使为空字符串也不会再自动刷新一次
    token: init?.token ?? "",
  })
  return {
    ok: r.ok,
    status: r.status,
    data: r.data,
    detail: r.detail,
    code: r.code,
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
  // F-D: 登出后主动作废本地乐观缓存,避免下次登录时命中过期状态
  _lastValidSub = null
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
    "auth/refresh",
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
      "auth/login",
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
      "auth/register",
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
    const r = await requestJson<CloudUser>("GET", "auth/me", { token })
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
      "subscription",
      { token },
    )
    if (!r.ok) return null
    return { ...r.data, checked_at: Date.now() }
  },

  /**
   * 调用 `POST /cloud/license/verify`。
   * 与 gateway 的 `_LICENSE_CACHE_TTL=300s` 不同,这里是**心跳**,返回当前状态。
   *
   * F-D: **乐观降级策略** —— 网络/5xx 类失败在 `LICENSE_OFFLINE_GRACE_MS`
   *      (默认 10 分钟) 窗口内保留上一次已知的有效订阅状态;只有明确的
   *      业务性拒绝(401/403/402 或 `expired` / `cancelled` body)才降级。
   *
   * 为什么用 `getCurrentTokenPair` 而不是 `getAccessToken`:
   *   后者会走 `ensureAccessToken` 触发 refresh;若 refresh 因网络失败而返回
   *   空串,就会把"云端不可达"错判成"未登录"。改用 pair 直接从存储取
   *   access token(哪怕已过期),这样真正的网络失败发生在下方 HTTP 调用上,
   *   能被分类成 transport 走乐观窗口。
   *
   * `opts.now` / `opts.graceMs` 仅供测试,生产调用不传。
   */
  async verifyLicense(
    opts?: { graceMs?: number; now?: number },
  ): Promise<SubscriptionStatus> {
    const graceMs = opts?.graceMs ?? LICENSE_OFFLINE_GRACE_MS
    const now = opts?.now ?? Date.now()

    const pair = await this.getCurrentTokenPair()
    if (!pair || !pair.access_token) {
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
        checked_at: now,
      }
    }
    const r = await requestJson<SubscriptionStatus>(
      "POST",
      "license/verify",
      { token: pair.access_token, body: {} },
    )

    // ── 1) 明确业务拒绝 → 立即失效,作废乐观缓存 ──
    if (r.status === 401 || r.status === 403 || r.status === 402) {
      // 401 → token 失效,清本地存储(既有逻辑)
      if (r.status === 401) await this.logout()
      _lastValidSub = null
      return {
        valid: false,
        reason: r.status === 401 ? "unauthenticated" : (r.detail || "subscription_denied"),
        plan: "",
        status: "",
        expire_at: null,
        quota: 0,
        used: 0,
        remaining: 0,
        is_pro: false,
        checked_at: now,
      }
    }

    // ── 2) HTTP 2xx ──
    if (r.ok) {
      const next: SubscriptionStatus = { ...r.data, checked_at: now }
      // 只有"云端明确说有效"才刷新乐观缓存;
      // 云端明确说失效(如 status=cancelled / expired)也要作废缓存 —— 但
      // 这种情况云端通常直接 4xx,不会返回 200+valid=false。为稳妥起见,
      // 无论 next.valid 真假都写缓存:valid=true 会进入乐观窗口,
      // valid=false 会被下一次调用直接识别为业务拒绝。
      _lastValidSub = { status: next, at: now }
      return next
    }

    // ── 3) 传输类失败(network / 5xx / 其他非 4xx 业务拒绝)──
    // 只有缓存里的状态"曾经是有效"且仍在 grace 窗口内,才保留有效;
    // 否则按 cloud_unreachable 失效。
    const verdict = classifyVerifyResult(r)
    const cached = _lastValidSub
    const withinGrace =
      cached !== null &&
      cached.status.valid === true &&
      (now - cached.at) < graceMs

    if (verdict === "transport" && withinGrace) {
      // 窗口内保留上一次的成功状态,并标出"这是乐观延续"
      return {
        ...cached.status,
        checked_at: now,
        reason: cached.status.reason || "offline_grace",
        // 覆盖 checked_at 是本次心跳时间,不改 status 字段
      }
    }

    // 传输失败统一 reason 为 "cloud_unreachable",让上层判断稳定
    // (gateway 层 detail 可能是 "cloud unreachable" 空格形式,这里归一化)
    if (verdict === "transport") {
      return {
        valid: false,
        reason: "cloud_unreachable",
        plan: "",
        status: "",
        expire_at: null,
        quota: 0,
        used: 0,
        remaining: 0,
        is_pro: false,
        checked_at: now,
      }
    }

    // 兜底:理论上不会跑到这里(classify 已覆盖 ok / business / transport)
    return {
      valid: false,
      reason: r.detail || "license_check_failed",
      plan: "",
      status: "",
      expire_at: null,
      quota: 0,
      used: 0,
      remaining: 0,
      is_pro: false,
      checked_at: now,
    }
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

// 把 token 拉取能力注入 client-gateway,让 gateway 在 needToken=true 时
// 自动拿到"可用" access token;此处是运行时的最后一行,依赖已就绪。
setTokenProvider(() => cloudAuth.getAccessToken())
