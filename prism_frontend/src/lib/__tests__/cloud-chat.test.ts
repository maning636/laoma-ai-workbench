import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// ──────────────────────────────────────────────────────────────
// Mock env.ts 给一个稳定的 URL 基线,避免依赖 .env
// ──────────────────────────────────────────────────────────────
vi.mock("@/lib/env", () => ({
  backendBaseUrl: "http://local.test",
  cloudBaseUrl: "http://cloud.test",
}))

import { chatViaCloud, serializeMessagesToPrompt, shouldFallBackToLocal } from "../cloud-chat"

// ──────────────────────────────────────────────────────────────
// Fetch mock 工具
// ──────────────────────────────────────────────────────────────

type FetchHandler = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Response | Promise<Response>

function jsonResponse(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

function sseResponse(chunks: string[]): Response {
  const enc = new TextEncoder()
  let i = 0
  return new Response(
    new ReadableStream<Uint8Array>({
      pull(controller) {
        if (i >= chunks.length) {
          controller.close()
          return
        }
        controller.enqueue(enc.encode(chunks[i++]))
      },
    }),
    {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    },
  )
}

function mockFetchSequence(handlers: Array<FetchHandler | Response>): ReturnType<typeof vi.fn> {
  const fn = vi.fn((async (_input: RequestInfo | URL, _init?: RequestInit) => {
    const next = handlers[handlers.length - 1]
    if (typeof next === "function") return next(_input, _init)
    return next
  }) as FetchHandler)
  let idx = 0
  // 用一个可变 wrapper 支持顺序消费
  const sequential = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const h = handlers[Math.min(idx, handlers.length - 1)]
      idx++
      if (typeof h === "function") return h(input, init)
      return h
    },
  )
  vi.stubGlobal("fetch", sequential)
  return sequential
}

function stubTokenProvider(token: string = "tok-1"): void {
  vi.doMock("@/lib/cloud-auth", () => ({
    cloudAuth: { getAccessToken: () => Promise.resolve(token) },
  }))
}

beforeEach(() => {
  vi.unstubAllGlobals()
  // 手动挂载 token provider —— client-gateway.setTokenProvider
  // 但为避免循环导入,这里用一个简单的 shim:把 fetch 里的 Authorization 头检查去掉。
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ══════════════════════════════════════════════════════════════
// serializeMessagesToPrompt —— 纯函数
// ══════════════════════════════════════════════════════════════
describe("serializeMessagesToPrompt", () => {
  it("空数组返回空串", () => {
    expect(serializeMessagesToPrompt([])).toBe("")
    expect(serializeMessagesToPrompt(undefined as any)).toBe("")
  })

  it("单条 user 消息序列化为 'User: ...'", () => {
    expect(serializeMessagesToPrompt([{ role: "user", content: "你好" }])).toBe(
      "User: 你好",
    )
  })

  it("多轮 user/assistant/system 混合", () => {
    const out = serializeMessagesToPrompt([
      { role: "system", content: "你是助手" },
      { role: "user", content: "你好" },
      { role: "assistant", content: "嗨,有什么需要?" },
      { role: "user", content: "再见" },
    ])
    expect(out).toBe(
      "System: 你是助手\nUser: 你好\nAssistant: 嗨,有什么需要?\nUser: 再见",
    )
  })

  it("空 content 消息被跳过", () => {
    const out = serializeMessagesToPrompt([
      { role: "user", content: "" },
      { role: "assistant", content: "  " },
      { role: "user", content: "真的问题" },
    ])
    expect(out).toBe("User: 真的问题")
  })
})

// ══════════════════════════════════════════════════════════════
// shouldFallBackToLocal —— 回落判定
// ══════════════════════════════════════════════════════════════
describe("shouldFallBackToLocal", () => {
  it("网络/认证/订阅/服务端错误 → true", () => {
    expect(shouldFallBackToLocal("network")).toBe(true)
    expect(shouldFallBackToLocal("unauthorized")).toBe(true)
    expect(shouldFallBackToLocal("subscription")).toBe(true)
    expect(shouldFallBackToLocal("server")).toBe(true)
  })

  it("客户端 4xx → false(本地修不好)", () => {
    expect(shouldFallBackToLocal("client")).toBe(false)
  })

  it("无 code → false", () => {
    expect(shouldFallBackToLocal(undefined)).toBe(false)
  })

  it("streaming not supported 的 detail → true", () => {
    expect(shouldFallBackToLocal("network", "streaming not supported")).toBe(true)
    expect(shouldFallBackToLocal("server", "streaming not supported")).toBe(true)
  })
})

// ══════════════════════════════════════════════════════════════
// chatViaCloud —— Tier 1: 云端流式成功
// ══════════════════════════════════════════════════════════════
describe("chatViaCloud / Tier 1 (cloud-stream)", () => {
  it("SSE 流成功 → source=cloud-stream, streaming=true, onDelta 按顺序触发", async () => {
    mockFetchSequence([
      sseResponse([
        'data: {"delta":"你"}\n\n',
        'data: {"delta":"好"}\n\n',
        'data: {"done":true,"tokens_in":3,"tokens_out":2}\n\n',
        "data: [DONE]\n\n",
      ]),
    ])

    const deltas: string[] = []
    const r = await chatViaCloud({
      messages: [{ role: "user", content: "你好" }],
      onDelta: (d) => deltas.push(d),
    })

    expect(r.ok).toBe(true)
    expect(r.streaming).toBe(true)
    expect(r.source).toBe("cloud-stream")
    expect(r.target).toBe("cloud")
    expect(r.text).toBe("你好")
    expect(deltas).toEqual(["你", "好"])
    expect(r.tokensIn).toBe(3)
    expect(r.tokensOut).toBe(2)
  })

  it("raw_prompt 模式下正确序列化 messages 到 body", async () => {
    const captured: Array<Record<string, unknown>> = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.body) captured.push(JSON.parse(String(init.body)))
        // 返回一个带 delta 的成功 SSE,避免触发 Tier 2 回落
        return sseResponse(['data: {"delta":"ok"}\n\ndata: [DONE]\n\n'])
      }),
    )
    await chatViaCloud({
      messages: [
        { role: "system", content: "你是助手" },
        { role: "user", content: "hi" },
      ],
    })
    expect(captured).toHaveLength(1)
    expect(captured[0].allow_raw).toBe(true)
    expect(typeof captured[0].raw_prompt).toBe("string")
    expect(captured[0].raw_prompt).toContain("System: 你是助手")
    expect(captured[0].raw_prompt).toContain("User: hi")
  })

  it("显式 promptName → 走 prompt_name + variables,不带 raw_prompt", async () => {
    const captured: Array<Record<string, unknown>> = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        if (init?.body) captured.push(JSON.parse(String(init.body)))
        // 返回带 delta 的成功 SSE,避免 text='' 触发 Tier 2 回落
        return sseResponse(['data: {"delta":"ok"}\n\ndata: [DONE]\n\n'])
      }),
    )
    await chatViaCloud({
      promptName: "platform_style.match",
      variables: { name: "小红书" },
      messages: [{ role: "user", content: "ignored" }],
    })
    expect(captured).toHaveLength(1)
    expect(captured[0].prompt_name).toBe("platform_style.match")
    expect(captured[0].variables).toEqual({ name: "小红书" })
    expect(captured[0].raw_prompt).toBeUndefined()
  })
})

// ══════════════════════════════════════════════════════════════
// chatViaCloud —— Tier 1 → Tier 2 回落 (cloud-stream → cloud-chat)
// ══════════════════════════════════════════════════════════════
describe("chatViaCloud / Tier 2 (cloud-chat fallback)", () => {
  it("云端流式返回 500(前置错误)→ 回落 /llm/chat 成功", async () => {
    const seq = mockFetchSequence([
      jsonResponse(500, { detail: "upstream down" }),
      jsonResponse(200, { content: "cloud chat says hi", tokens_in: 5, tokens_out: 3 }),
    ])
    const r = await chatViaCloud({
      messages: [{ role: "user", content: "hi" }],
    })
    expect(seq).toHaveBeenCalledTimes(2)
    expect(r.ok).toBe(true)
    expect(r.source).toBe("cloud-chat")
    expect(r.streaming).toBe(false)
    expect(r.text).toBe("cloud chat says hi")
    expect(r.tokensIn).toBe(5)
    expect(r.tokensOut).toBe(3)
  })

  it("云端流式返回 401(unauthorized)→ 回落 /llm/chat", async () => {
    mockFetchSequence([
      jsonResponse(401, { detail: "token expired" }),
      jsonResponse(200, { content: "still got content" }),
    ])
    const r = await chatViaCloud({
      messages: [{ role: "user", content: "hi" }],
    })
    expect(r.ok).toBe(true)
    expect(r.source).toBe("cloud-chat")
    expect(r.text).toBe("still got content")
  })

  it("云端流式返回 402(subscription)→ 回落 /llm/chat", async () => {
    mockFetchSequence([
      jsonResponse(402, { detail: "quota exceeded" }),
      jsonResponse(200, { content: "chat ok" }),
    ])
    const r = await chatViaCloud({ messages: [{ role: "user", content: "x" }] })
    expect(r.source).toBe("cloud-chat")
    expect(r.text).toBe("chat ok")
  })

  it("云端流式中途收到 event: error(无 delta)→ 回落 /llm/chat", async () => {
    mockFetchSequence([
      sseResponse([
        'event: error\ndata: {"error":"upstream boom"}\n\n',
        "data: [DONE]\n\n",
      ]),
      jsonResponse(200, { content: "recovered" }),
    ])
    const r = await chatViaCloud({ messages: [{ role: "user", content: "x" }] })
    expect(r.ok).toBe(true)
    expect(r.source).toBe("cloud-chat")
    expect(r.text).toBe("recovered")
  })
})

// ══════════════════════════════════════════════════════════════
// chatViaCloud —— Tier 1 部分成功(有 delta 后失败)不再回落
// ══════════════════════════════════════════════════════════════
describe("chatViaCloud / 部分流式不做二次回落", () => {
  it("流式拿到部分 delta 后 fetch 断开 → 保留已有文本,不回落到 /chat", async () => {
    // 第一段正常出 delta,第二段触发 read 抛错
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        let i = 0
        const enc = new TextEncoder()
        const chunks = [
          enc.encode('data: {"delta":"部分"}\n\n'),
        ]
        return new Response(
          new ReadableStream<Uint8Array>({
            pull(controller) {
              if (i >= chunks.length) {
                // 触发读失败(gatewayStream 里的 try/catch 会走 onError + 返回 ok=false)
                const err = new Error("read failed")
                controller.error(err)
                return
              }
              controller.enqueue(chunks[i++])
            },
          }),
          { status: 200, headers: { "Content-Type": "text/event-stream" } },
        )
      }),
    )
    const r = await chatViaCloud({ messages: [{ role: "user", content: "x" }] })
    // 期望:ok=false,但 text 已保留,且**没有**再向 /llm/chat 发请求
    expect(r.ok).toBe(false)
    expect(r.source).toBe("cloud-stream")
    expect(r.text).toBe("部分")
    expect((globalThis.fetch as any).mock.calls.length).toBe(1)
  })
})

// ══════════════════════════════════════════════════════════════
// chatViaCloud —— Tier 3: 本地非流式回落
// ══════════════════════════════════════════════════════════════
describe("chatViaCloud / Tier 3 (local-chat fallback)", () => {
  it("云端 503(不可达) + /llm/chat 也 503 → 回落 /api/v1/ai/chat", async () => {
    mockFetchSequence([
      jsonResponse(503, { detail: "upstream down" }),
      jsonResponse(503, { detail: "upstream down" }),
      jsonResponse(200, { content: "local reply" }),
    ])
    const r = await chatViaCloud({ messages: [{ role: "user", content: "hi" }] })
    expect(r.ok).toBe(true)
    expect(r.source).toBe("local-chat")
    expect(r.target).toBe("local")
    expect(r.streaming).toBe(false)
    expect(r.text).toBe("local reply")
  })

  it("云端网络错误(fetch 抛 TypeError)→ 回落本地", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockRejectedValueOnce(new TypeError("ECONNREFUSED")) // stream fetch 失败
        .mockRejectedValueOnce(new TypeError("ECONNREFUSED")) // chat fetch 也失败
        .mockResolvedValueOnce(
          new Response(JSON.stringify({ content: "local ok" }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        ),
    )
    const r = await chatViaCloud({ messages: [{ role: "user", content: "hi" }] })
    expect(r.ok).toBe(true)
    expect(r.source).toBe("local-chat")
    expect(r.text).toBe("local ok")
  })

  it("三层全挂 → ok=false, code='local_failed',detail 包含 cloud 侧原因", async () => {
    mockFetchSequence([
      jsonResponse(503, { detail: "stream down" }),
      jsonResponse(503, { detail: "chat down" }),
      jsonResponse(500, { detail: "local down" }),
    ])
    const r = await chatViaCloud({ messages: [{ role: "user", content: "x" }] })
    expect(r.ok).toBe(false)
    expect(r.source).toBe("local-chat")
    expect(r.code).toBe("local_failed")
    expect(r.detail).toContain("cloud")
  })

  it("只有 promptName 无 messages → 云端失败时不能落到本地(没有 raw messages)", async () => {
    mockFetchSequence([
      jsonResponse(503, { detail: "cloud down" }),
      jsonResponse(503, { detail: "cloud down" }),
    ])
    const r = await chatViaCloud({ promptName: "p1", variables: { a: 1 } })
    expect(r.ok).toBe(false)
    expect(r.source).toBe("local-chat")
    expect(r.detail).toContain("no messages")
  })
})

// ══════════════════════════════════════════════════════════════
// chatViaCloud —— Abort 传播
// ══════════════════════════════════════════════════════════════
describe("chatViaCloud / Abort", () => {
  it("AbortController.abort() 后 stream 抛 AbortError → code='aborted',不回落到 chat/local", async () => {
    const ctrl = new AbortController()
    ctrl.abort()
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(
        new DOMException("The operation was aborted.", "AbortError"),
      ),
    )
    const r = await chatViaCloud({
      messages: [{ role: "user", content: "x" }],
      signal: ctrl.signal,
    })
    expect(r.ok).toBe(false)
    expect(r.code).toBe("aborted")
    // 只调过一次(stream 层),没有触发 chat/local
    expect((globalThis.fetch as any).mock.calls.length).toBe(1)
  })
})

// ══════════════════════════════════════════════════════════════
// chatViaCloud —— 云端 4xx 硬失败,不回落
// ══════════════════════════════════════════════════════════════
describe("chatViaCloud / 云端硬失败不回落", () => {
  it("云端 /llm/chat 返回 400(如 raw 校验失败)→ 不回落本地", async () => {
    mockFetchSequence([
      jsonResponse(400, { detail: "stream 4xx" }),
      jsonResponse(400, { detail: "prompt_name not found" }),
    ])
    const r = await chatViaCloud({ promptName: "unknown", variables: {} })
    expect(r.ok).toBe(false)
    expect(r.source).toBe("cloud-chat")
    expect(r.code).toBe("client")
    expect(r.detail).toBe("prompt_name not found")
  })
})
