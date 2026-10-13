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

// ──────────────────────────────────────────────────────────────
// SSE 流式扩展点
// ──────────────────────────────────────────────────────────────

/** 一帧 SSE `message` 事件的解析结果。 */
export interface GatewayStreamFrame {
  /** 事件类型(默认 "message")。 */
  event: string
  /** `data:` 字段的原文(多行以 `\n` 拼接),`[DONE]` 时保留字面量。 */
  data: string
}

/** 每帧的解析结果 —— 由 `onFrame` 回调接收。 */
export interface GatewayStreamFrameParsed extends GatewayStreamFrame {
  /** 若 `data` 是合法 JSON,则是解析对象;否则 `undefined`。 */
  json?: unknown
}

export interface GatewayStreamOptions extends GatewayRequestOptions {
  /** 收到每一帧(含 `[DONE]`)时回调。抛异常会终止流。 */
  onFrame?: (frame: GatewayStreamFrameParsed) => void
  /** 仅收到普通 message 帧的 `delta` 文本时回调(便捷:自动 JSON 解析)。 */
  onDelta?: (delta: string) => void
  /** 收到终止标记 `[DONE]` 时回调。 */
  onDone?: (meta?: unknown) => void
  /** 收到 `event: error` 帧或 transport 失败时回调。 */
  onError?: (err: { code: GatewayErrorCode; status: number; detail?: string }) => void
  /** 允许外部 AbortSignal 中断(SSE 流通常不主动超时)。 */
  signal?: AbortSignal
}

/** 流结束时的元信息。 */
export interface GatewayStreamResult {
  ok: boolean
  status: number
  target: GatewayTarget
  /** 累计的 message 帧 JSON 对象数组(不含 `[DONE]`)。 */
  frames: unknown[]
  /** 累计的 `delta` 拼接后的文本(若帧含 `delta` 字段)。 */
  text: string
  /** 终止帧 `[DONE]` 之前的最后一个 done 帧(若有)。 */
  meta?: { tokens_in?: number; tokens_out?: number }
  code?: GatewayErrorCode
  detail?: string
}

/**
 * 解析 SSE 文本流为一串帧。
 *
 * 规则(遵循 WHATWG EventSource 规范的最小实现):
 *   - 帧分隔:`\n\n` 或 `\r\n\r\n`(容忍两种换行)
 *   - 帧内每行:`field: value` 或 `field:value`(`:` 后空格可选)
 *   - 多行 `data:` 拼接为同一帧的 `data`(以 `\n` 连接)
 *   - 空字段行与以 `:` 开头的注释行忽略
 *   - 事件字段缺失时,`event` 默认 `"message"`
 *
 * 半帧缓冲:数据可能被分块返回,本函数会消耗所有完整帧,
 * 并把剩余的不完整部分作为返回值,调用方应在下一轮把它拼回前面。
 */
export function parseSSEStream(
  text: string,
  onFrame: (frame: GatewayStreamFrame) => void,
): string {
  // 归一化换行:所有 \r\n / \r → \n,便于后续统一用 \n\n 分帧。
  let buffer = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n")

  while (true) {
    const idx = buffer.indexOf("\n\n")
    if (idx === -1) break

    const rawFrame = buffer.slice(0, idx)
    buffer = buffer.slice(idx + 2)

    if (!rawFrame.trim()) {
      // 空帧忽略
      continue
    }

    const lines = rawFrame.split("\n")
    let event = "message"
    const dataParts: string[] = []
    let sawAny = false

    for (const line of lines) {
      if (!line) continue
      if (line.startsWith(":")) continue // 注释行
      const colon = line.indexOf(":")
      let field: string
      let value: string
      if (colon === -1) {
        field = line
        value = ""
      } else {
        field = line.slice(0, colon)
        value = line.slice(colon + 1)
        // 规范:value 前若有一个空格,去掉;其他保留
        if (value.charCodeAt(0) === 0x20) value = value.slice(1)
      }
      if (field === "event") {
        event = value
        sawAny = true
      } else if (field === "data") {
        dataParts.push(value)
        sawAny = true
      }
      // 其他字段(id / retry)当前忽略 —— LLM 代理不需要
    }

    if (sawAny) {
      onFrame({ event, data: dataParts.join("\n") })
    }
  }

  // 返回剩余的不完整部分,由调用方累积到下一轮
  return buffer
}

/**
 * 流式请求(基于 fetch + SSE 解析)。
 *
 * 与 `gatewayRequest` 共享:
 *   - 目标解析(`resolveTarget` / `resolveUrl`)
 *   - token 注入(`resolveAccessToken`)
 *   - 错误归一化(`normalizeCode`)
 *
 * 差异:
 *   - **不做** 超时(流式通常长时间运行,由调用方 `signal` 控制)
 *   - **不解析 JSON**;直接把 SSE 帧交给 `onFrame` / `onDelta` / `onDone`
 *   - 返回 `GatewayStreamResult`(累计的 frames / text / meta)
 *
 * 前置错误(401/402/403/404/422/5xx)在收到 HTTP 状态时立即走 onError + 返回,
 * 不进入 SSE 解析 —— 与后端 `/cloud/llm/stream` 的约定一致。
 */
export async function gatewayStream(
  opts: GatewayStreamOptions,
): Promise<GatewayStreamResult> {
  const method = (opts.method || "POST").toUpperCase()
  const target = resolveTarget(opts.feature)
  const url = resolveUrl(opts.feature, opts.path, target)
  const token = await resolveAccessToken(opts)

  const headers = buildHeaders({ Accept: "text/event-stream", ...(opts.headers || {}) }, token)

  let resp: Response
  try {
    resp = await fetch(url, {
      method,
      headers,
      credentials: "omit",
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      signal: opts.signal,
    })
  } catch (e: unknown) {
    const err = e as { name?: string; message?: string }
    const aborted = err?.name === "AbortError"
    const code: GatewayErrorCode = aborted ? "client" : "network"
    opts.onError?.({ code, status: 0, detail: aborted ? "aborted" : "cloud unreachable" })
    return {
      ok: false,
      status: 0,
      target,
      frames: [],
      text: "",
      code,
      detail: aborted ? "aborted" : "cloud unreachable",
    }
  }

  // 前置错误:不进入 SSE 解析
  if (!resp.ok) {
    let detail: string | undefined
    try {
      const bodyData: unknown = await resp.json()
      if (bodyData && typeof bodyData === "object" && typeof (bodyData as any).detail === "string") {
        detail = (bodyData as any).detail
      }
    } catch {
      /* 非 JSON 响应,忽略 */
    }
    const code = normalizeCode(resp.status)
    opts.onError?.({ code, status: resp.status, detail })
    return {
      ok: false,
      status: resp.status,
      target,
      frames: [],
      text: "",
      code,
      detail,
    }
  }

  // 读取 SSE 流
  if (!resp.body || typeof resp.body.getReader !== "function") {
    const code: GatewayErrorCode = "network"
    opts.onError?.({ code, status: resp.status, detail: "streaming not supported" })
    return {
      ok: false,
      status: resp.status,
      target,
      frames: [],
      text: "",
      code,
      detail: "streaming not supported",
    }
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder("utf-8")
  let buffer = ""
  const frames: unknown[] = []
  let text = ""
  let meta: { tokens_in?: number; tokens_out?: number } | undefined

  const handleFrame = (frame: GatewayStreamFrame): void => {
    // [DONE] 帧:标记完成,不进入 JSON 解析(它本身就是终止字面量)
    if (frame.data === "[DONE]") {
      opts.onFrame?.({ event: frame.event, data: frame.data, json: undefined })
      return
    }
    let json: unknown = undefined
    try {
      json = JSON.parse(frame.data)
      frames.push(json)
      if (frame.event === "error") {
        const detail =
          json && typeof json === "object" && typeof (json as any).error === "string"
            ? (json as any).error
            : undefined
        opts.onError?.({ code: "server", status: resp.status, detail })
        return
      }
      if (json && typeof json === "object") {
        if (typeof (json as any).delta === "string") {
          text += (json as any).delta
          opts.onDelta?.((json as any).delta)
        }
        if ((json as any).done === true) {
          meta = {
            tokens_in:
              typeof (json as any).tokens_in === "number"
                ? (json as any).tokens_in
                : undefined,
            tokens_out:
              typeof (json as any).tokens_out === "number"
                ? (json as any).tokens_out
                : undefined,
          }
        }
      }
    } catch {
      // 非 JSON data(极少数情况,如纯文本增量);保留原始 data
      if (frame.data && frame.event !== "error") {
        text += frame.data
        opts.onDelta?.(frame.data)
      }
    }
    opts.onFrame?.({ event: frame.event, data: frame.data, json })
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      // 跨 chunk 累积:parseSSEStream 只消耗完整帧,残留的半帧留到下一轮拼接
      buffer += decoder.decode(value, { stream: true })
      buffer = parseSSEStream(buffer, handleFrame)
    }
    // 冲刷 decoder 尾部字节
    buffer += decoder.decode()
    // SSE 协议:完整流一定以 \n\n 结尾;剩余半帧按残缺丢弃。
    opts.onDone?.(meta)
  } catch (e: unknown) {
    const err = e as { name?: string; message?: string }
    const aborted = err?.name === "AbortError"
    const code: GatewayErrorCode = aborted ? "client" : "network"
    const detail = aborted ? "aborted" : (err?.message || "stream interrupted")
    opts.onError?.({ code, status: resp.status, detail })
    return {
      ok: aborted,
      status: resp.status,
      target,
      frames,
      text,
      meta,
      code: aborted ? undefined : code,
      detail: aborted ? undefined : detail,
    }
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* 已释放 */
    }
  }

  return { ok: true, status: resp.status, target, frames, text, meta }
}

/** 便捷别名,方便业务侧阅读。 */
export const clientGateway = {
  request: gatewayRequest,
  stream: gatewayStream,
  setTokenProvider,
  resolveTarget,
  resolveUrl,
  parseSSEStream,
}

/** 云端 feature 白名单,导出给上层做检查/测试。 */
export { CLOUD_FEATURES }
