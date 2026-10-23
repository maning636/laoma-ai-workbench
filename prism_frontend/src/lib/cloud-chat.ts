/**
 * F-A: 云端 LLM 对话高层封装 —— 流式优先,非流式回落。
 *
 * 与 `client-gateway.ts` 分工:
 *   - client-gateway 只做"单发请求 / SSE 单帧解析",不感知业务。
 *   - 本模块负责**语义路径**:
 *       1. 首选 `POST /cloud/llm/stream` (SSE) —— 逐字 onDelta。
 *       2. 云端流式失败 → 回落 `POST /cloud/llm/chat` (JSON,同一次订阅)。
 *       3. 云端整体不可用 → 回落 `POST /api/v1/ai/chat` (本地后端)。
 *
 * 关键约定:
 *   - 云端 chat 走 `{prompt_name, variables}` 或 `{raw_prompt, allow_raw}`;
 *     不原生支持多轮 messages。因此本模块把 OpenAI 风格 messages 序列化为
 *     单一 `raw_prompt`(需 `allow_raw: true`),这样既保留多轮语义,
 *     又不改后端 `/cloud/llm/chat` 契约。
 *   - 若显式传入 `promptName`,则以 prompt_name + variables 走云端库,
 *     不使用 raw_prompt(即使 messages 里有历史)。
 *   - 若调用方已拿到 partial text(流式解到一半再失败),**不再回落到 chat**,
 *     避免同一 prompt 在云端被消费两次额度。
 *   - 云端完全失败(网络 / 401 / 403 / 402 / 5xx / streaming unsupported)时,
 *     才尝试本地非流式 —— 保住"聊天不能挂"的底线。
 *
 * 触发回落到本地非流式的条件(与 UI 报告口径一致):
 *   - `code === "network"` (云端 host 不可达 / DNS / CORS)
 *   - `code === "unauthorized"` (未登录 / token 失效)
 *   - `code === "subscription"` (云端订阅额度已用尽)
 *   - `code === "server"` (云端 5xx / 上游异常)
 *   - `detail === "streaming not supported"` (响应缺 body / 老浏览器)
 *   - `code === "client"` (AbortError 除外) —— 客户端中断**不回落**
 *   - 收到 `event: error` 帧且尚无 delta —— 云端上游异常,尝试非流式
 *
 * 依赖:client-gateway (gatewayStream / gatewayRequest / GatewayErrorCode)
 * 无依赖:cloud-auth (token 注入由 gateway 通过 setTokenProvider 拿到)
 */

import {
  gatewayRequest,
  gatewayStream,
  type GatewayErrorCode,
} from "./client-gateway"

// ──────────────────────────────────────────────────────────────
// 类型
// ──────────────────────────────────────────────────────────────

export type ChatRole = "user" | "assistant" | "system"

export interface ChatMessage {
  role: ChatRole
  content: string
}

export interface ChatViaCloudOptions {
  /**
   * OpenAI 兼容的消息序列。
   * 若同时传了 `promptName`,messages 会被忽略 —— 云端走 prompt 库。
   */
  messages?: ChatMessage[]
  /** 云端 prompt 库名(优先于 messages/rawPrompt)。 */
  promptName?: string
  /** prompt 变量,配合 promptName 使用。 */
  variables?: Record<string, unknown>
  /** 显式原始 prompt(需 allowRaw=true 才生效)。 */
  rawPrompt?: string
  allowRaw?: boolean
  model?: string
  temperature?: number
  maxTokens?: number
  /** AbortSignal —— 会同步到所有层级的 fetch。 */
  signal?: AbortSignal
  /** 每收到一个 delta 文本时的回调。仅云端流式生效。 */
  onDelta?: (delta: string) => void
  /**
   * 跳过云端两层(Tier1 流式 / Tier2 非流式),直接走本地(Tier3)。
   *
   * P7 用法:探测到云端 LLM **明确未配置**(`api_key_configured === false`)时置 true,
   * 这样用户就不会先吃两次必然失败的云端请求(每次都带网络往返 + 额度校验),
   * 而是一步落到本地对话。
   *
   * 注意:只有"明确未配置"才该置 true。探测失败/网络抖动属于 unknown,
   * 此时**保持 false**(走原有三层回落),不能因为一次抖动就降级到本地。
   */
  skipCloud?: boolean
}

export type ChatViaCloudSource = "cloud-stream" | "cloud-chat" | "local-chat"

export interface ChatViaCloudResult {
  ok: boolean
  /** 最终完整回复文本(拼接所有 delta / 或 chat.content / 或本地 chat.content)。 */
  text: string
  /** 是否走了云端流式路径(逐字显示)。 */
  streaming: boolean
  /** 实际命中的目标(用于报告/日志)。 */
  target: "cloud" | "local"
  /** 最终来源端点。 */
  source: ChatViaCloudSource
  tokensIn?: number
  tokensOut?: number
  /** 失败时的语义错误码;成功时 undefined。 */
  code?: GatewayErrorCode | "local_failed" | "aborted"
  detail?: string
}

// ──────────────────────────────────────────────────────────────
// 内部工具
// ──────────────────────────────────────────────────────────────

/**
 * 把多轮 messages 序列化为一个 raw_prompt。
 *
 * 约定:
 *   - system 消息 → "System: ..."
 *   - assistant → "Assistant: ..."
 *   - user → "User: ..."
 *   - 空 content 跳过
 *   - 空数组返回空串(调用方应保证最后一条是 user)
 */
export function serializeMessagesToPrompt(
  messages: ChatMessage[],
): string {
  if (!messages || messages.length === 0) return ""
  const parts: string[] = []
  for (const m of messages) {
    const content = (m?.content ?? "").trim()
    if (!content) continue
    const role = (m.role || "user").toLowerCase() as ChatRole
    if (role === "system") parts.push(`System: ${content}`)
    else if (role === "assistant") parts.push(`Assistant: ${content}`)
    else parts.push(`User: ${content}`)
  }
  return parts.join("\n")
}

/** 组装云端的 ChatRequest 请求体。 */
function buildCloudPayload(opts: ChatViaCloudOptions): Record<string, unknown> {
  const payload: Record<string, unknown> = {}
  if (opts.promptName) {
    payload.prompt_name = opts.promptName
    payload.variables = opts.variables ?? {}
  } else {
    const raw = opts.rawPrompt ?? serializeMessagesToPrompt(opts.messages ?? [])
    payload.raw_prompt = raw
    payload.allow_raw = opts.allowRaw ?? true
  }
  if (opts.model) payload.model = opts.model
  if (opts.temperature !== undefined) payload.temperature = opts.temperature
  if (opts.maxTokens !== undefined) payload.max_tokens = opts.maxTokens
  return payload
}

function isAborted(err?: { name?: string }): boolean {
  return !!err && err.name === "AbortError"
}

// ──────────────────────────────────────────────────────────────
// 主入口:三层回落
// ──────────────────────────────────────────────────────────────

/**
 * 云端优先的对话入口:
 *   1. POST /cloud/llm/stream (SSE 流式,带 token)
 *   2. → POST /cloud/llm/chat (JSON 非流式,带 token)
 *   3. → POST /api/v1/ai/chat (本地后端,不带 token)
 *
 * 三层之间的回落由 `chatViaCloudFallsBack` 判断 —— 见注释里的条件表。
 */
export async function chatViaCloud(
  opts: ChatViaCloudOptions,
): Promise<ChatViaCloudResult> {
  const payload = buildCloudPayload(opts)

  // ═══════ Tier 0: 明确跳过云端 ═══════
  // 服务端明确回「云端 LLM 未配置」时,云端两层必然失败 —— 直接落到本地,
  // 省掉两次注定失败的往返(Tier1 流式 + Tier2 非流式)。
  if (opts.skipCloud) {
    return chatViaLocalFallback(opts, {
      cloudCode: "server",
      cloudDetail: "云端 AI 未配置，已跳过云端对话",
    })
  }

  // ═══════ Tier 1: 云端流式 ═══════
  type StreamErrInfo = { code: GatewayErrorCode; status: number; detail?: string }
  const errHolder: { err: StreamErrInfo | null } = { err: null }

  const streamResult = await gatewayStream({
    feature: "llm",
    path: "llm/stream",
    method: "POST",
    body: payload,
    needToken: true,
    signal: opts.signal,
    onDelta: opts.onDelta,
    onError: (err) => {
      errHolder.err = err
    },
  })

  // 用户主动 Abort —— 直接终止,不再回落
  const streamErr = errHolder.err
  if (streamResult.code === "client" && streamResult.detail === "aborted") {
    return {
      ok: false,
      text: streamResult.text,
      streaming: true,
      target: "cloud",
      source: "cloud-stream",
      code: "aborted",
      detail: "aborted",
    }
  }

  // 云端流式成功:HTTP ok + 至少拿到一点文本(避免空流回落再撞一次)
  const streamText = streamResult.text || ""
  if (streamResult.ok && streamText && !streamErr) {
    return {
      ok: true,
      text: streamText,
      streaming: true,
      target: "cloud",
      source: "cloud-stream",
      tokensIn: streamResult.meta?.tokens_in,
      tokensOut: streamResult.meta?.tokens_out,
    }
  }

  // 拿到部分文本但中途出错 —— **不回落**,避免重复消费额度
  // UI 已经显示了部分内容,应该继续展示已有的流。
  // (此分支能进到说明 !streamResult.ok || streamErr,即 streamErr 至少为真 或 ok=false)
  if (streamText) {
    const errCode: GatewayErrorCode | undefined =
      streamErr?.code ?? streamResult.code
    const errDetail: string | undefined =
      streamErr?.detail ?? streamResult.detail
    return {
      ok: false,
      text: streamText,
      streaming: false,
      target: "cloud",
      source: "cloud-stream",
      code: errCode,
      detail: errDetail,
    }
  }

  // 无文本 + 失败 → 尝试 Tier 2:云端非流式
  const fallbackCode: GatewayErrorCode | undefined =
    streamErr?.code ?? streamResult.code
  const fallbackDetail: string | undefined =
    streamErr?.detail ?? streamResult.detail

  // 调用方已 abort,直接终止,不再尝试云端 chat
  if (opts.signal?.aborted) {
    return {
      ok: false,
      text: "",
      streaming: false,
      target: "cloud",
      source: "cloud-stream",
      code: "aborted",
      detail: "aborted",
    }
  }

  // ═══════ Tier 2: 云端非流式 ═══════
  // gatewayRequest 无 signal 参数;此处用 fetch 默认 + timeoutMs 兜底。
  // 若 stream 阶段已被 abort 会提前 return(见上面分支)。
  const chatResp = await gatewayRequest<any>({
    feature: "llm",
    path: "llm/chat",
    method: "POST",
    body: payload,
    needToken: true,
  })

  if (chatResp.ok) {
    const data = (chatResp.data && typeof chatResp.data === "object"
      ? chatResp.data
      : {}) as Record<string, unknown>
    const text = typeof data.content === "string" ? data.content : ""
    return {
      ok: true,
      text,
      streaming: false,
      target: "cloud",
      source: "cloud-chat",
      tokensIn: typeof data.tokens_in === "number" ? (data.tokens_in as number) : undefined,
      tokensOut: typeof data.tokens_out === "number" ? (data.tokens_out as number) : undefined,
    }
  }

  // 云端整体不可用 → Tier 3:本地非流式
  if (shouldFallBackToLocal(chatResp.code, chatResp.detail)) {
    return chatViaLocalFallback(opts, {
      cloudCode: chatResp.code ?? fallbackCode,
      cloudDetail: chatResp.detail || fallbackDetail,
    })
  }

  // 云端明确拒绝(如 raw_prompt 校验失败),不再回落到本地,避免混淆语义
  return {
    ok: false,
    text: "",
    streaming: false,
    target: "cloud",
    source: "cloud-chat",
    code: chatResp.code ?? fallbackCode,
    detail: chatResp.detail || fallbackDetail,
  }
}

// ──────────────────────────────────────────────────────────────
// 回落判定 & Tier 3:本地非流式
// ──────────────────────────────────────────────────────────────

/**
 * 判断云端失败是否应该继续回落到本地。
 *
 * 规则:
 *   - 网络 / 认证 / 订阅额度 / 服务端错误 → 回落
 *   - 客户端 4xx(如 prompt 校验失败)→ 不回落(本地也不会修好)
 *   - abort → 不回落(用户主动中断)
 */
export function shouldFallBackToLocal(
  code?: GatewayErrorCode,
  detail?: string,
): boolean {
  if (!code) return false
  if (code === "network" || code === "unauthorized" || code === "subscription" || code === "server") {
    return true
  }
  if (detail === "streaming not supported") return true
  return false
}

async function chatViaLocalFallback(
  opts: ChatViaCloudOptions,
  cloudErr: { cloudCode?: GatewayErrorCode; cloudDetail?: string },
): Promise<ChatViaCloudResult> {
  // 只有传了 messages 才有意义;若调用方走的是 promptName 模式,本地不支持,直接失败。
  if (!opts.messages || opts.messages.length === 0) {
    return {
      ok: false,
      text: "",
      streaming: false,
      target: "local",
      source: "local-chat",
      code: cloudErr.cloudCode ?? "network",
      detail: `cloud failed and no messages provided for local fallback: ${cloudErr.cloudDetail || ""}`.trim(),
    }
  }

  try {
    const resp = await fetch("/api/v1/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: opts.signal,
      body: JSON.stringify({
        messages: opts.messages,
        stream: false,
      }),
    })

    if (!resp.ok) {
      const text = await resp.text().catch(() => "")
      return {
        ok: false,
        text: "",
        streaming: false,
        target: "local",
        source: "local-chat",
        code: "local_failed",
        detail: `local chat HTTP ${resp.status}: ${text.slice(0, 200) || ""} (cloud: ${cloudErr.cloudDetail || cloudErr.cloudCode})`.trim(),
      }
    }

    const data = (await resp.json().catch(() => ({}))) as Record<string, unknown>
    const text = typeof data.content === "string" ? data.content
      : typeof data.response === "string" ? data.response
      : ""
    return {
      ok: true,
      text,
      streaming: false,
      target: "local",
      source: "local-chat",
    }
  } catch (e: unknown) {
    const aborted = isAborted(e as { name?: string })
    return {
      ok: false,
      text: "",
      streaming: false,
      target: "local",
      source: "local-chat",
      code: aborted ? "aborted" : "local_failed",
      detail: aborted
        ? "aborted"
        : `local chat failed: ${e instanceof Error ? e.message : String(e)} (cloud: ${cloudErr.cloudDetail || cloudErr.cloudCode})`.trim(),
    }
  }
}

/** 供测试用的导出:暴露内部工具。 */
export const _internal = {
  buildCloudPayload,
  serializeMessagesToPrompt,
}
