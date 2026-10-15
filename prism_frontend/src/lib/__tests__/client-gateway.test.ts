import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// ──────────────────────────────────────────────────────────────
// 用工厂 mock env.ts,给 URL 断言一个稳定、易读的基线。
// (env.ts 的默认值是 127.0.0.1:7000 / api.prism.local,也能跑,
//  但用 mock 更直观,断言里一眼就能看出 cloud / local 前缀差异。)
// ──────────────────────────────────────────────────────────────
vi.mock("@/lib/env", () => ({
  backendBaseUrl: "http://local.test",
  cloudBaseUrl: "http://cloud.test",
}))

import {
  gatewayRequest,
  gatewayStream,
  parseSSEStream,
  setTokenProvider,
  resolveUrl,
  type GatewayRequestOptions,
  type GatewayStreamOptions,
} from "../client-gateway"

// ──────────────────────────────────────────────────────────────
// fetch mock 构造器
// ──────────────────────────────────────────────────────────────

type FetchHandler = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Response | Promise<Response>

function mockFetchOnce(handler: FetchHandler): {
  fn: ReturnType<typeof vi.fn>
  calls: () => Array<{ input: RequestInfo | URL; init?: RequestInit }>
} {
  const fn = vi.fn(handler)
  vi.stubGlobal("fetch", fn)
  // 用惰性函数拿 calls: 调用时刻 fn 还没跑,calls 一定是空的
  const calls = () =>
    (fn as any).mock.calls.map(
      (c: any[]) => ({ input: c[0], init: c[1] }),
    )
  return { fn, calls }
}

function jsonResponse(
  status: number,
  body: unknown = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

// 构造一个可控 chunk 序列的 SSE Response(用于 gatewayStream 测试)
function sseResponse(chunks: Uint8Array[]): Response {
  let i = 0
  return new Response(
    new ReadableStream<Uint8Array>({
      pull(controller) {
        if (i >= chunks.length) {
          controller.close()
          return
        }
        controller.enqueue(chunks[i++])
      },
    }),
    {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    },
  )
}

const enc = new TextEncoder()
const strToBytes = (s: string): Uint8Array => enc.encode(s)
// 任意字节数组(用于把 UTF-8 字符拆到两个 chunk 里制造半帧/半码点)
const bytes = (...b: number[]): Uint8Array =>
  new Uint8Array(b)

// ──────────────────────────────────────────────────────────────
// 全局钩子:每次测试都清一遍 token provider + fetch stub,避免相互污染
// ──────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.unstubAllGlobals()
  setTokenProvider(null)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ══════════════════════════════════════════════════════════════
// resolveUrl —— 双通道 URL 拼接
// ══════════════════════════════════════════════════════════════
describe("resolveUrl / 路由", () => {
  it("feature='cloud' + auth/login → http://cloud.test/cloud/auth/login", () => {
    expect(
      resolveUrl("cloud", "auth/login"),
    ).toBe("http://cloud.test/cloud/auth/login")
  })

  it("feature='cloud' 时 path 已含 'cloud/' 前缀 → 不重复拼", () => {
    expect(
      resolveUrl("cloud", "cloud/auth/login"),
    ).toBe("http://cloud.test/cloud/auth/login")
  })

  it("feature='llm'(云端白名单)+ llm/chat → 自动补 cloud/", () => {
    expect(
      resolveUrl("llm", "llm/chat"),
    ).toBe("http://cloud.test/cloud/llm/chat")
  })

  it("feature='local' + files/stats → 补 api/v1/ 前缀", () => {
    expect(
      resolveUrl("local", "files/stats/summary"),
    ).toBe("http://local.test/api/v1/files/stats/summary")
  })

  it("feature='local' 时 path 已含 'api/' 前缀 → 不重复拼 api/v1", () => {
    expect(
      resolveUrl("local", "api/v1/ping"),
    ).toBe("http://local.test/api/v1/ping")
  })
})

// ══════════════════════════════════════════════════════════════
// gatewayRequest —— 错误归一化(状态码 → code)
// ══════════════════════════════════════════════════════════════
describe("gatewayRequest / 错误归一化", () => {
  const base: GatewayRequestOptions = {
    feature: "llm",
    path: "llm/chat",
    method: "GET",
  }

  it("401 → code='unauthorized', detail 提取自响应体", async () => {
    mockFetchOnce(() => jsonResponse(401, { detail: "token expired" }))
    const r = await gatewayRequest(base)
    expect(r.ok).toBe(false)
    expect(r.status).toBe(401)
    expect(r.code).toBe("unauthorized")
    expect(r.detail).toBe("token expired")
    expect(r.target).toBe("cloud")
  })

  it("402 → code='subscription'", async () => {
    mockFetchOnce(() => jsonResponse(402, { detail: "quota exceeded" }))
    const r = await gatewayRequest(base)
    expect(r.code).toBe("subscription")
    expect(r.status).toBe(402)
  })

  it("500 → code='server'", async () => {
    mockFetchOnce(() => jsonResponse(500, { detail: "boom" }))
    const r = await gatewayRequest(base)
    expect(r.code).toBe("server")
  })

  it("503 → code='server'", async () => {
    mockFetchOnce(() => jsonResponse(503, { detail: "upstream down" }))
    const r = await gatewayRequest(base)
    expect(r.code).toBe("server")
  })

  it("400 / 404 等其他 4xx → code='client'", async () => {
    const { calls, fn } = mockFetchOnce(() => jsonResponse(404, {}))
    const r = await gatewayRequest(base)
    expect(r.code).toBe("client")
    expect(r.status).toBe(404)
    // 顺便断言 URL 拼装(避免路由回退到 localhost)
    expect(String(calls()[0].input)).toBe(
      "http://cloud.test/cloud/llm/chat",
    )
    expect(typeof fn).toBe("function")
  })

  it("网络异常(fetch 抛错) → code='network', status=0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    )
    const r = await gatewayRequest(base)
    expect(r.ok).toBe(false)
    expect(r.status).toBe(0)
    expect(r.code).toBe("network")
    expect(r.detail).toBe("cloud unreachable")
  })

  it("正常 2xx + JSON body → ok=true, data 保留解析结果", async () => {
    mockFetchOnce(() => jsonResponse(200, { hello: "world", n: 7 }))
    const r = await gatewayRequest<{ hello: string; n: number }>(base)
    expect(r.ok).toBe(true)
    expect(r.status).toBe(200)
    expect(r.code).toBeUndefined()
    expect(r.data).toEqual({ hello: "world", n: 7 })
  })
})

// ══════════════════════════════════════════════════════════════
// gatewayRequest —— token 注入
// ══════════════════════════════════════════════════════════════
describe("gatewayRequest / token 注入", () => {
  const base: GatewayRequestOptions = {
    feature: "llm",
    path: "llm/chat",
    method: "GET",
  }

  it("默认不注入 Authorization(needToken 未开启、未显式 token)", async () => {
    const { calls } = mockFetchOnce(() => jsonResponse(200, {}))
    await gatewayRequest(base)
    const headers = calls()[0].init?.headers as Record<string, string>
    expect(headers["Authorization"]).toBeUndefined()
    // 但 Content-Type / Accept 依旧由 buildHeaders 加上
    expect(headers["Content-Type"]).toBe("application/json")
    expect(headers["Accept"]).toBe("application/json")
  })

  it("needToken:true + setTokenProvider → provider 被调用,注入 Authorization", async () => {
    const provider = vi.fn().mockResolvedValue("tok-abc-123")
    setTokenProvider(provider)
    const { calls } = mockFetchOnce(() => jsonResponse(200, {}))
    await gatewayRequest({ ...base, needToken: true })
    expect(provider).toHaveBeenCalledTimes(1)
    const headers = calls()[0].init?.headers as Record<string, string>
    expect(headers["Authorization"]).toBe("Bearer tok-abc-123")
  })

  it("显式 token 覆盖 provider(优先于 needToken)", async () => {
    const provider = vi.fn().mockResolvedValue("should-not-be-used")
    setTokenProvider(provider)
    const { calls } = mockFetchOnce(() => jsonResponse(200, {}))
    await gatewayRequest({ ...base, needToken: true, token: "explicit-tok" })
    const headers = calls()[0].init?.headers as Record<string, string>
    // 关键断言:provider 一次都没被调用
    expect(provider).not.toHaveBeenCalled()
    expect(headers["Authorization"]).toBe("Bearer explicit-tok")
  })

  it("provider 返回空串 → 不注入 Authorization", async () => {
    setTokenProvider(vi.fn().mockResolvedValue(""))
    const { calls } = mockFetchOnce(() => jsonResponse(200, {}))
    await gatewayRequest({ ...base, needToken: true })
    const headers = calls()[0].init?.headers as Record<string, string>
    expect(headers["Authorization"]).toBeUndefined()
  })

  it("显式 token='' 会覆盖 needToken,且不注入 Authorization", async () => {
    const provider = vi.fn().mockResolvedValue("should-be-skipped")
    setTokenProvider(provider)
    const { calls } = mockFetchOnce(() => jsonResponse(200, {}))
    await gatewayRequest({ ...base, needToken: true, token: "" })
    // token 分支先 return 空串,provider 完全没被调用
    expect(provider).not.toHaveBeenCalled()
    const headers = calls()[0].init?.headers as Record<string, string>
    expect(headers["Authorization"]).toBeUndefined()
  })

  it("云端白名单外 feature 归到 local(路由回归)", async () => {
    const { calls } = mockFetchOnce(() => jsonResponse(200, {}))
    const r = await gatewayRequest({
      feature: "local",
      path: "ping",
      method: "GET",
    })
    expect(r.target).toBe("local")
    expect(String(calls()[0].input)).toBe("http://local.test/api/v1/ping")
  })
})

// ══════════════════════════════════════════════════════════════
// parseSSEStream —— SSE 帧解析
// ══════════════════════════════════════════════════════════════
describe("parseSSEStream / 帧解析", () => {
  function collectFrames(
    input: string,
  ): { frames: Array<{ event: string; data: string }>; leftover: string } {
    const frames: Array<{ event: string; data: string }> = []
    const leftover = parseSSEStream(input, (f) => frames.push(f))
    return { frames, leftover }
  }

  it("半帧跨 chunk 缓冲:第一次调用只吃掉能解析的完整帧,剩余留作 buffer", () => {
    // 第一段只有半个 data 字段(没 \n\n 结尾),parseSSEStream 应原样返回它
    const part1 = "data: hello\n" // 无 \n\n 结尾 → 半帧
    const r1 = collectFrames(part1)
    expect(r1.frames).toEqual([])
    expect(r1.leftover).toBe("data: hello\n")

    // 第二段以 \n 起头,把上一段拼成一个完整的 "hello" 帧,然后自带另一帧 "world"
    const part2 = "\ndata: world\n\n"
    const r2 = collectFrames(r1.leftover + part2)
    expect(r2.frames).toEqual([
      { event: "message", data: "hello" },
      { event: "message", data: "world" },
    ])
    expect(r2.leftover).toBe("")
  })

  it("多行 data: 拼接为同一帧(以 \\n 连接)", () => {
    const { frames } = collectFrames(
      "data: hello\n\ndata: line1\ndata: line2\ndata: line3\n\n",
    )
    expect(frames).toEqual([
      { event: "message", data: "hello" },
      { event: "message", data: "line1\nline2\nline3" },
    ])
  })

  it("[DONE] 作为独立帧发出(解析层不做语义处理,只做文本切分)", () => {
    const { frames } = collectFrames("data: [DONE]\n\n")
    expect(frames).toEqual([{ event: "message", data: "[DONE]" }])
  })

  it("CRLF 换行被归一化(与 LF 等价)", () => {
    const { frames } = collectFrames("data: hello\r\n\r\ndata: world\r\n\r\n")
    expect(frames).toEqual([
      { event: "message", data: "hello" },
      { event: "message", data: "world" },
    ])
  })

  it("空帧 / 空行被跳过,不产生假帧", () => {
    const { frames } = collectFrames(
      "\n\n\n\ndata: real\n\n\n\nevent: named\ndata: xyz\n\n",
    )
    expect(frames).toEqual([
      { event: "message", data: "real" },
      { event: "named", data: "xyz" },
    ])
  })

  it("UTF-8 多字节字符被 chunk 切断:半字节由上层累积后再喂入仍正确解码", () => {
    // "中好" 的 UTF-8 字节 = E4 B8 AD E5 A5 BD
    // chunk1 拿到 "data: " 前缀 + "中" 完整 3 字节 + "好" 的前 1 字节(E5);
    // chunk2 拿到 "好" 剩余 2 字节(A5 BD) + "\n\n" 帧终止符。
    // 关键点:如果只按 chunk 边界解码,E5 是半字节,应该被 TextDecoder({stream:true}) 保留。
    const prefix = "data: "
    const prefixBytes = enc.encode(prefix)
    const chunk1 = bytes(
      ...prefixBytes,
      0xe4, 0xb8, 0xad, 0xe5, 0xa5, // "中"(完整) + "好" 的前 2 字节
    )
    const chunk2 = bytes(0xbd, 0x0a, 0x0a) // "好" 尾 1 字节 + \n\n

    // gatewayStream 内部用 TextDecoder({stream:true}) 累积半字节,
    // parseSSEStream 只处理文本层 —— 这里模拟同样的两段拼接。
    const decoder = new TextDecoder("utf-8")
    let buffer = ""
    const frames: Array<{ event: string; data: string }> = []

    buffer += decoder.decode(chunk1, { stream: true })
    buffer = parseSSEStream(buffer, (f) => frames.push(f))
    // 第一遍:decode 得到 "data: 中" + "好" 的前 2 字节(U+597D 前 2 字节),
    // 没有 \n\n 终止符 → 整段留在 buffer,不产生任何帧。
    expect(frames).toEqual([])
    expect(buffer.startsWith("data: 中")).toBe(true)

    buffer += decoder.decode(chunk2, { stream: true })
    buffer += decoder.decode() // 冲刷尾部
    buffer = parseSSEStream(buffer, (f) => frames.push(f))

    // 关键断言:两 chunk 拼接后 decode 出完整的 "中好",parseSSEStream 正确解出该帧。
    expect(frames).toEqual([{ event: "message", data: "中好" }])
    expect(buffer).toBe("")
  })
})

// ══════════════════════════════════════════════════════════════
// gatewayStream —— SSE 流式请求
// ══════════════════════════════════════════════════════════════
describe("gatewayStream / 流式请求", () => {
  const base: GatewayStreamOptions = {
    feature: "llm",
    path: "llm/stream",
    method: "POST",
    body: { messages: [] },
  }

  it("onDone 正常路径下恰好触发一次,frames / text 累计正确", async () => {
    const chunks = [
      strToBytes('data: {"delta":"你"}\n\n'),
      strToBytes('data: {"delta":"好"}\n\n'),
      strToBytes('data: {"done":true,"tokens_in":3,"tokens_out":2}\n\n'),
      strToBytes('data: [DONE]\n\n'),
    ]
    mockFetchOnce(() => sseResponse(chunks))

    const onDone = vi.fn()
    const deltas: string[] = []
    const r = await gatewayStream({
      ...base,
      onDone,
      onDelta: (d) => deltas.push(d),
    })

    expect(r.ok).toBe(true)
    expect(r.text).toBe("你好")
    expect(deltas).toEqual(["你", "好"])
    // frames 累计到 2 个 message 帧 + 1 个 done 帧,不含 [DONE]
    expect(r.frames).toHaveLength(3)
    expect(r.meta).toEqual({ tokens_in: 3, tokens_out: 2 })
    expect(onDone).toHaveBeenCalledTimes(1)
    // onDone 收到 meta 作为参数
    expect(onDone).toHaveBeenCalledWith({ tokens_in: 3, tokens_out: 2 })
  })

  it("上游 event: error 帧触发 onError(code='server'),detail 从 .error 字段取", async () => {
    const chunks = [
      strToBytes('data: {"delta":"ok"}\n\n'),
      strToBytes('event: error\ndata: {"error":"quota exceeded"}\n\n'),
      strToBytes('data: [DONE]\n\n'),
    ]
    mockFetchOnce(() => sseResponse(chunks))

    const onError = vi.fn()
    const r = await gatewayStream({ ...base, onError })

    expect(onError).toHaveBeenCalledTimes(1)
    const arg = onError.mock.calls[0][0] as any
    expect(arg.code).toBe("server")
    expect(arg.status).toBe(200)
    expect(arg.detail).toBe("quota exceeded")
    // 实现细节:handleFrame 里 error 帧的 JSON 已经先 push 进 frames,再触发 onError
    // (client-gateway.ts:516-524)。所以 frames 长度是 2 = "ok" 帧 + error 帧本身。
    expect(r.text).toBe("ok")
    expect(r.frames).toHaveLength(2)
    expect(r.frames[1]).toEqual({ error: "quota exceeded" })
    expect(r.ok).toBe(true) // 从 HTTP 视角仍 ok
  })

  it("HTTP 401 前置错误 → 不进 SSE 解析,直接 onError(code='unauthorized')", async () => {
    mockFetchOnce(() =>
      jsonResponse(401, { detail: "unauthorized" }),
    )
    const onError = vi.fn()
    const r = await gatewayStream({ ...base, onError })
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0]).toMatchObject({
      code: "unauthorized",
      status: 401,
      detail: "unauthorized",
    })
    expect(r.ok).toBe(false)
    expect(r.code).toBe("unauthorized")
    expect(r.frames).toEqual([])
  })

  it("HTTP 500 前置错误 → onError(code='server')", async () => {
    mockFetchOnce(() => jsonResponse(500, { detail: "boom" }))
    const onError = vi.fn()
    const r = await gatewayStream({ ...base, onError })
    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0]).toMatchObject({
      code: "server",
      status: 500,
    })
    expect(r.code).toBe("server")
  })

  it("外部 AbortSignal 已 aborted 时 fetch 抛 AbortError → code='client'", async () => {
    const ctrl = new AbortController()
    ctrl.abort()
    const fetchFn = vi.fn().mockRejectedValue(
      new DOMException("The operation was aborted.", "AbortError"),
    )
    vi.stubGlobal("fetch", fetchFn)

    const onError = vi.fn()
    const r = await gatewayStream({ ...base, signal: ctrl.signal, onError })

    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError.mock.calls[0][0]).toMatchObject({
      code: "client",
      status: 0,
      detail: "aborted",
    })
    expect(r.ok).toBe(false)
    expect(r.code).toBe("client")
  })

  it("fetch 层普通网络错误 → code='network', detail='cloud unreachable'", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("ECONNREFUSED")),
    )
    const onError = vi.fn()
    const r = await gatewayStream({ ...base, onError })
    expect(r.ok).toBe(false)
    expect(r.code).toBe("network")
    expect(r.detail).toBe("cloud unreachable")
    expect(onError).toHaveBeenCalledTimes(1)
  })

  it("跨 chunk 的 SSE 帧:parseSSEStream 缓冲 + TextDecoder({stream:true}) 拼回正常帧", async () => {
    // 一个 message 帧被切成两段,再跟一个 [DONE]
    const full = 'data: {"delta":"跨chunk"}\n\ndata: [DONE]\n\n'
    const mid = Math.floor(full.length / 2)
    mockFetchOnce(() => sseResponse([strToBytes(full.slice(0, mid)), strToBytes(full.slice(mid))]))

    const onDone = vi.fn()
    const deltas: string[] = []
    const r = await gatewayStream({
      ...base,
      onDone,
      onDelta: (d) => deltas.push(d),
    })

    expect(deltas).toEqual(["跨chunk"])
    expect(r.text).toBe("跨chunk")
    expect(r.frames).toHaveLength(1)
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it("onFrame 对每个帧(含 [DONE])都会被调用", async () => {
    const chunks = [
      strToBytes('data: {"delta":"a"}\n\n'),
      strToBytes('data: [DONE]\n\n'),
    ]
    mockFetchOnce(() => sseResponse(chunks))

    const onFrame = vi.fn()
    await gatewayStream({ ...base, onFrame })

    expect(onFrame).toHaveBeenCalledTimes(2)
    // [DONE] 帧的 json 字段为 undefined(实现里显式不做 JSON.parse)
    expect(onFrame.mock.calls[0][0]).toMatchObject({
      event: "message",
      data: '{"delta":"a"}',
      json: { delta: "a" },
    })
    expect(onFrame.mock.calls[1][0]).toMatchObject({
      event: "message",
      data: "[DONE]",
      json: undefined,
    })
  })

  it("云端流式走 cloud base URL 且不重复拼 cloud/", async () => {
    const fetchFn = vi.fn((..._args: any[]) =>
      sseResponse([strToBytes("data: [DONE]\n\n")]),
    )
    vi.stubGlobal("fetch", fetchFn)
    await gatewayStream({ ...base, feature: "llm" })
    const firstCall = (fetchFn as any).mock.calls[0]
    expect(String(firstCall?.[0])).toBe(
      "http://cloud.test/cloud/llm/stream",
    )
  })
})
