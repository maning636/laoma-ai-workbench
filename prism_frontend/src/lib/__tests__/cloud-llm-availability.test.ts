import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// Mock env.ts 给一个稳定的 URL 基线,避免依赖 .env
vi.mock("@/lib/env", () => ({
  backendBaseUrl: "http://local.test",
  cloudBaseUrl: "http://cloud.test",
}))

import {
  CLOUD_LLM_PROBE_TIMEOUT_MS,
  describeCloudLlmAvailability,
  probeCloudLlmAvailability,
  resolveCloudLlmAvailability,
  shouldHideCloudLlmEntry,
} from "../cloud-llm-availability"

// ══════════════════════════════════════════════════════════════
// resolveCloudLlmAvailability —— 纯函数,判定三态
// ══════════════════════════════════════════════════════════════
describe("resolveCloudLlmAvailability", () => {
  it("available:false(明确未配置)→ unavailable", () => {
    const r = resolveCloudLlmAvailability({ api_key_configured: false })
    expect(r.availability).toBe("unavailable")
  })

  it("available:true → available", () => {
    const r = resolveCloudLlmAvailability({ api_key_configured: true })
    expect(r.availability).toBe("available")
  })

  it("优先认 available 字段(后端新字段)", () => {
    const r = resolveCloudLlmAvailability({
      available: false,
      api_key_configured: true,
    })
    expect(r.availability).toBe("unavailable")
  })

  it("只有 available 字段(无 api_key_configured)也能判定", () => {
    expect(resolveCloudLlmAvailability({ available: false }).availability).toBe(
      "unavailable",
    )
    expect(resolveCloudLlmAvailability({ available: true }).availability).toBe(
      "available",
    )
  })

  it("★ 空对象 → unknown(不认识就是不认识,不能当成未配置)", () => {
    const r = resolveCloudLlmAvailability({})
    expect(r.availability).toBe("unknown")
    expect(r.reason).toBe("unrecognized_payload")
  })

  it("★ null / undefined / 非对象 → unknown", () => {
    expect(resolveCloudLlmAvailability(null).availability).toBe("unknown")
    expect(resolveCloudLlmAvailability(undefined).availability).toBe("unknown")
    expect(resolveCloudLlmAvailability("nope").availability).toBe("unknown")
    expect(resolveCloudLlmAvailability(42).availability).toBe("unknown")
  })

  it("★ 字段类型不对(字符串 'false')→ unknown,不当成未配置", () => {
    const r = resolveCloudLlmAvailability({ api_key_configured: "false" })
    expect(r.availability).toBe("unknown")
  })

  it("透传服务端的中文 message", () => {
    const r = resolveCloudLlmAvailability({
      api_key_configured: false,
      message: "云端 AI 未配置：服务端未设置 CLOUD_LLM_API_KEY。",
    })
    expect(r.availability).toBe("unavailable")
    expect(r.message).toContain("CLOUD_LLM_API_KEY")
  })
})

// ══════════════════════════════════════════════════════════════
// shouldHideCloudLlmEntry —— 隐藏判定的核心不变量
// ══════════════════════════════════════════════════════════════
describe("shouldHideCloudLlmEntry", () => {
  it("★ 只有 unavailable 才隐藏入口", () => {
    expect(shouldHideCloudLlmEntry("unavailable")).toBe(true)
  })

  it("★ unknown 绝不隐藏(网络抖动不能误伤正常用户)", () => {
    expect(shouldHideCloudLlmEntry("unknown")).toBe(false)
  })

  it("available 不隐藏", () => {
    expect(shouldHideCloudLlmEntry("available")).toBe(false)
  })

  it("null / undefined 不隐藏", () => {
    expect(shouldHideCloudLlmEntry(null)).toBe(false)
    expect(shouldHideCloudLlmEntry(undefined)).toBe(false)
  })
})

// ══════════════════════════════════════════════════════════════
// describeCloudLlmAvailability —— 文案
// ══════════════════════════════════════════════════════════════
describe("describeCloudLlmAvailability", () => {
  it("unavailable → 中文说明提到 CLOUD_LLM_API_KEY 与本地替代方案", () => {
    const text = describeCloudLlmAvailability("unavailable")
    expect(text).toContain("CLOUD_LLM_API_KEY")
    expect(text).toContain("本地模型")
  })

  it("unavailable + 服务端 message → 优先用服务端的", () => {
    const text = describeCloudLlmAvailability("unavailable", "服务端原话")
    expect(text).toBe("服务端原话")
  })

  it("unknown → 说明是探测失败,而不是说没配", () => {
    const text = describeCloudLlmAvailability("unknown")
    expect(text).toContain("未知")
    expect(text).not.toContain("CLOUD_LLM_API_KEY")
  })
})

// ══════════════════════════════════════════════════════════════
// probeCloudLlmAvailability —— 走网络的部分
// ══════════════════════════════════════════════════════════════
describe("probeCloudLlmAvailability", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function jsonResponse(status: number, body: unknown): Response {
    return new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    })
  }

  it("服务端回未配置 → unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(200, { api_key_configured: false })),
    )
    const r = await probeCloudLlmAvailability()
    expect(r.availability).toBe("unavailable")
  })

  it("服务端回已配置 → available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(200, { api_key_configured: true })),
    )
    const r = await probeCloudLlmAvailability()
    expect(r.availability).toBe("available")
  })

  it("★ 网络不可达 → unknown(不是 unavailable)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("ECONNREFUSED")))
    const r = await probeCloudLlmAvailability()
    expect(r.availability).toBe("unknown")
    expect(r.reason).toContain("probe_failed")
  })

  it("★ 5xx → unknown", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(503, {})))
    const r = await probeCloudLlmAvailability()
    expect(r.availability).toBe("unknown")
  })

  it("★ 404(老部署没有该端点)→ unknown", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(404, {})))
    const r = await probeCloudLlmAvailability()
    expect(r.availability).toBe("unknown")
  })

  it("★ 200 但形状不认识 → unknown", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, { foo: "bar" })))
    const r = await probeCloudLlmAvailability()
    expect(r.availability).toBe("unknown")
  })

  it("★ 200 非 JSON → unknown", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("<html>proxy error</html>", { status: 200 })),
    )
    const r = await probeCloudLlmAvailability()
    expect(r.availability).toBe("unknown")
  })

  it("探测请求不带 token(health 允许匿名)", async () => {
    const captured: Array<{ url: string; headers: Record<string, unknown> }> = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        captured.push({
          url: String(_input),
          headers: (init?.headers ?? {}) as Record<string, unknown>,
        })
        return jsonResponse(200, { api_key_configured: true })
      }),
    )
    await probeCloudLlmAvailability()
    expect(captured).toHaveLength(1)
    expect(String(captured[0].url)).toContain("/cloud/llm/health")
    const auth = (captured[0].headers as Record<string, unknown>).Authorization
    expect(auth === undefined || auth === "").toBe(true)
  })

  it("使用默认超时常量", () => {
    expect(CLOUD_LLM_PROBE_TIMEOUT_MS).toBe(5_000)
  })
})
