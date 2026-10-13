/**
 * 前端统一网关(client-gateway)。
 *
 * 与 `prism_backend/fusion_ai/cloud_gateway.py` (C16) 对齐的浏览器侧镜像,
 * 目的:把"云端 vs 本地"路由、token 注入、错误归一化收敛到一层,
 * 让上层(`cloud-auth.ts` 等)不再自己拼 `API_ENDPOINTS.cloud*` 或手写
 * `fetch` + 401 处理。
 *
 * 路由规则:
 *   - feature ∈ {auth, subscription, license, usage, llm, billing} → **云端**
 *       (`cloudBaseUrl`,与后端 gateway 一样保留 `/cloud` 前缀)
 *   - 其他 → **本地** (`backendBaseUrl`,自动补 `/api/v1/` 前缀)
 *
 * Token 注入:
 *   - `needToken: true` 时通过 `getTokenProvider` 从 cloud-auth 拉取
 *     一个"可用" access token(必要时自动 refresh)
 *   - `token: "<literal>"` 显式覆盖,用于 refresh 等无 token 场景
 *
 * 错误归一化:
 *   - 网络/DNS/CORS → "network"
 *   - 401/403       → "unauthorized"
 *   - 402           → "subscription"(订阅额度已用尽)
 *   - 5xx           → "server"
 *   - 其他 4xx      → "client"
 *
 * 依赖方向:
 *   - client-gateway 不 import cloud-auth,避免循环依赖。
 *   - `cloud-auth` 在初始化末尾调用 `setTokenProvider()` 把
 *     `cloudAuth.getAccessToken` 注入进来,让 gateway 无需直接依赖 cloud-auth。
 */

import { backendBaseUrl, cloudBaseUrl } from "./env"

// ──────────────────────────────────────────────────────────────
// 类型
// ──────────────────────────────────────────────────────────────

export type GatewayFeature =
  | "auth"
  | "subscription"
  | "license"
  | "usage"
  | "llm"
  | "billing"
  | "local"
  | string

export type GatewayTarget = "cloud" | "local"

export type GatewayErrorCode =
  | "network"
  | "unauthorized"
  | "subscription"
  | "server"
  | "client"
  | "missing_token"

export interface GatewayResult<T = unknown> {
  ok: boolean
  status: number
  target: GatewayTarget
  data: T
  detail?: string
  /** 只在 `!ok` 时提供;上层用这个做 UI 分支。 */
  code?: GatewayErrorCode
}

export interface GatewayRequestOptions {
  /** 与后端 gateway 语义一致的 feature 名;显式 "cloud" / "local" 亦可。 */
  feature: GatewayFeature
  /** 相对路径,例如 `"auth/login"`、`"license/verify"`、`"files/stats/summary"`。 */
  path: string
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE"
  body?: unknown
  headers?: Record<string, string>
  /** 自动从 cloud-auth 拉 access token;默认 false(登录/注册等无 token 场景)。 */
  needToken?: boolean
  /** 显式覆盖,优先于 `needToken`。传空字符串会跳过注入。 */
  token?: string
  /** 超时(毫秒);不传则用 fetch 默认。 */
  timeoutMs?: number
}

export type TokenProvider = () => Promise<string>

// ──────────────────────────────────────────────────────────────
// Token 注入桥接
// ──────────────────────────────────────────────────────────────

let _tokenProvider: TokenProvider | null = null

/** 由 cloud-auth 在初始化时调用;之后 gateway 走这条通道拿 access token。 */
export function setTokenProvider(fn: TokenProvider | null): void {
  _tokenProvider = fn
}

async function resolveAccessToken(opts: GatewayRequestOptions): Promise<string> {
  if (opts.token !== undefined) return opts.token
  if (!opts.needToken) return ""
  if (!_tokenProvider) return ""
  const tok = await _tokenProvider()
  return typeof tok === "string" ? tok : ""
}

// ──────────────────────────────────────────────────────────────
// Feature → 目标(云端/本地)判定
// ──────────────────────────────────────────────────────────────

const CLOUD_FEATURES: ReadonlySet<string> = new Set([
  "auth",
  "subscription",
  "license",
  "usage",
  "llm",
  "billing",
])

/** 显式 `"cloud"` / `"local"` 也当 target 用;feature 白名单之外一律 local。 */
export function resolveTarget(feature: GatewayFeature): GatewayTarget {
  const f = (feature || "").trim().toLowerCase()
  if (f === "cloud") return "cloud"
  if (f === "local") return "local"
  return CLOUD_FEATURES.has(f) ? "cloud" : "local"
}

/**
 * 解析出最终 URL。
 *
 * 云端约定(与后端 gateway 与 `env.ts.API_ENDPOINTS.cloud*` 兼容):
 *   - path 已带 `cloud/` 前缀 → 直接拼接
 *   - 否则自动补 `cloud/`
 *
 * 注意:`env.ts.cloudBaseUrl` 的规范化把用户填的 `.../cloud` 后缀剥掉
 * (见 `normalizeCloudBaseUrl`),所以拼接后一定包含 `/cloud/` 段;
 * 与后端 gateway `_resolve_route` 行为一致。
 *
 * 本地约定:
 *   - path 已带 `api/` 前缀 → 直接拼接
 *   - 否则自动补 `api/v1/`
 *
 * 完整 URL 走 URL 对象归一化,避免多次 `//` 或尾部 `/`。
 */
export function resolveUrl(
  feature: GatewayFeature,
  path: string,
  target?: GatewayTarget,
): string {
  const tgt = target ?? resolveTarget(feature)
  const cleanPath = (path || "").trim().replace(/^\/+/, "").replace(/\/+$/, "")
  const base = tgt === "cloud" ? cloudBaseUrl : backendBaseUrl

  if (!cleanPath) {
    return base
  }

  let finalPath: string
  if (tgt === "cloud") {
    if (cleanPath.startsWith("cloud/")) {
      finalPath = cleanPath
    } else if (cleanPath === "cloud") {
      finalPath = "cloud"
    } else {
      finalPath = `cloud/${cleanPath}`
    }
  } else {
    if (cleanPath.startsWith("api/")) {
      finalPath = cleanPath
    } else {
      finalPath = `api/v1/${cleanPath}`
    }
  }

  return new URL(finalPath, base + "/").toString()
}

// ──────────────────────────────────────────────────────────────
// HTTP 传输
// ──────────────────────────────────────────────────────────────

function buildHeaders(
  headers: Record<string, string> | undefined,
  token: string,
): Record<string, string> {
  const h: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(headers || {}),
  }
  if (token) h["Authorization"] = `Bearer ${token}`
  return h
}

async function doFetch(
  method: string,
  url: string,
  headers: Record<string, string>,
  body: unknown,
  timeoutMs?: number,
): Promise<Response> {
  const init: RequestInit = {
    method,
    headers,
    credentials: "omit",
    body: body === undefined ? undefined : JSON.stringify(body),
  }
  if (timeoutMs && timeoutMs > 0 && typeof AbortController !== "undefined") {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), timeoutMs)
    init.signal = ctrl.signal
    try {
      return await fetch(url, init)
    } finally {
      clearTimeout(timer)
    }
  }
  return fetch(url, init)
}

async function parseJsonSafe(resp: Response): Promise<unknown> {
  try {
    return await resp.json()
  } catch {
    return {}
  }
}

/** 归一化:HTTP 状态码 → 语义错误码。 */
function normalizeCode(status: number): GatewayErrorCode {
  if (status === 401 || status === 403) return "unauthorized"
  if (status === 402) return "subscription"
  if (status >= 500) return "server"
  return "client"
}

// ──────────────────────────────────────────────────────────────
// 对外主入口
// ──────────────────────────────────────────────────────────────

/**
 * 统一网关请求。返回结构化的 `GatewayResult`,不抛异常;调用方按 `code` 分支。
 *
 * 约定:
 *   - `ok: true` 当且仅当 HTTP 2xx 且能解析出 JSON(即便 body 是 `{}`)。
 *   - `data` 是解析后的 JSON;非 JSON 响应会得到 `{}`。
 *   - `code` 只在 `!ok` 时给出,且一定为 `GatewayErrorCode` 之一。
 */
export async function gatewayRequest<T = unknown>(
  opts: GatewayRequestOptions,
): Promise<GatewayResult<T>> {
  const method = (opts.method || "GET").toUpperCase()
  const target = resolveTarget(opts.feature)
  const url = resolveUrl(opts.feature, opts.path, target)
  const token = await resolveAccessToken(opts)

  let resp: Response
  try {
    resp = await doFetch(
      method,
      url,
      buildHeaders(opts.headers, token),
      opts.body,
      opts.timeoutMs,
    )
  } catch {
    return {
      ok: false,
      status: 0,
      target,
      data: {} as T,
      code: "network",
      detail: "cloud unreachable",
    }
  }

  const data = (await parseJsonSafe(resp)) as T
  const detail =
    data && typeof data === "object" && typeof (data as any).detail === "string"
      ? (data as any).detail
      : undefined

  if (resp.ok) {
    return { ok: true, status: resp.status, target, data, detail }
  }
  return {
    ok: false,
    status: resp.status,
    target,
    data,
    detail,
    code: normalizeCode(resp.status),
  }
}

/** 便捷别名,方便业务侧阅读。 */
export const clientGateway = {
  request: gatewayRequest,
  setTokenProvider,
  resolveTarget,
  resolveUrl,
}

/** 云端 feature 白名单,导出给上层做检查/测试。 */
export { CLOUD_FEATURES }
