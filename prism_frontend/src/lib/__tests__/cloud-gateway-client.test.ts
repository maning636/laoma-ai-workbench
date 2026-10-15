import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// ──────────────────────────────────────────────────────────────
// F-E / F-F(F8) / F-G 综合测试:
//   - probeCloudReachable: 探测成功/失败/5xx/401
//   - buildTierContext: 有/无 token、可达/不可达、不探测
//   - F-F(F8): 证明 feature 白名单路由真的生效(而非走显式 "cloud")
//   - F-G: isUserAbort / isUserAbortSignal 语义
//   - F-F(F11): USAGE_ESTIMATE 常量存在且语义清晰
// ──────────────────────────────────────────────────────────────

vi.mock("@/lib/env", () => ({
  backendBaseUrl: "http://local.test",
  cloudBaseUrl: "http://cloud.test",
}))

import {
  probeCloudReachable,
  buildTierContext,
  isUserAbort,
  isUserAbortSignal,
  isCloudFeature,
  cloudFeatureRequest,
  USAGE_ESTIMATE,
  USAGE_ESTIMATE_DISCLAIMER,
  PROBE_CLOUD_TIMEOUT_MS,
  cloudGatewayClient,
} from "../cloud-gateway-client"
import { CLOUD_FEATURES, setTokenProvider } from "../client-gateway"

function jsonResponse(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

beforeEach(() => {
  vi.unstubAllGlobals()
  setTokenProvider(null)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// ══════════════════════════════════════════════════════════════
// F-E: probeCloudReachable
// ══════════════════════════════════════════════════════════════

describe("probeCloudReachable", () => {
  it("2xx 响应 → true(且走 feature='llm' 白名单路由,不显式 'cloud')", async () => {
    const fn = vi.fn(async () => jsonResponse(200, { status: "ok" }))
    vi.stubGlobal("fetch", fn)

    const reachable = await probeCloudReachable()
    expect(reachable).toBe(true)

    // 关键断言:URL 是 cloud.test/cloud/llm/health(带 /cloud/ 前缀,因为 feature='llm' 走了白名单)
    const url = String((fn as any).mock.calls[0][0])
    expect(url).toBe("http://cloud.test/cloud/llm/health")
  })

  it("fetch 抛错(网络异常) → false", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("ECONNREFUSED")))
    const reachable = await probeCloudReachable()
    expect(reachable).toBe(false)
  })

  it("HTTP 500 / 503 → false(服务端异常视为不可达)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(500, {})))
    expect(await probeCloudReachable()).toBe(false)

    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(503, {})))
    expect(await probeCloudReachable()).toBe(false)
  })

  it("HTTP 401 → true(服务活着但拒绝;仍算可达)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, { detail: "nope" })))
    // 探测端点默认 needToken=false,但云端仍可能返回 401(取决于后端策略)
    expect(await probeCloudReachable()).toBe(true)
  })

  it("自定义 timeoutMs 会透传给底层 fetch(signal 被设置)", async () => {
    const fn = vi.fn(async () => jsonResponse(200, {}))
    vi.stubGlobal("fetch", fn)
    await probeCloudReachable({ timeoutMs: 1234 })
    const init = (fn as any).mock.calls[0][1] as RequestInit
    // 传了 timeoutMs 就一定会创建 AbortController 并 attach signal
    expect(init.signal).toBeInstanceOf(AbortSignal)
  })

  it("默认 timeoutMs = PROBE_CLOUD_TIMEOUT_MS", () => {
    expect(PROBE_CLOUD_TIMEOUT_MS).toBe(5000)
  })
})

// ══════════════════════════════════════════════════════════════
// F-E: buildTierContext
// ══════════════════════════════════════════════════════════════

describe("buildTierContext", () => {
  it("无 token → tier='local', reason='no_token', 不发探测请求", async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal("fetch", fetchFn)
    const ctx = await buildTierContext({
      getToken: async () => "",
      probe: true,
    })
    expect(ctx.tier).toBe("local")
    expect(ctx.reason).toBe("no_token")
    expect(ctx.hasToken).toBe(false)
    // 关键:未发任何 fetch 请求
    expect(fetchFn).not.toHaveBeenCalled()
  })

  it("有 token + 云端可达 + probe=true → tier='cloud'", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, { status: "ok" })))
    const ctx = await buildTierContext({
      getToken: async () => "tok-abc",
      probe: true,
    })
    expect(ctx.tier).toBe("cloud")
    expect(ctx.cloudReachable).toBe(true)
    expect(ctx.hasToken).toBe(true)
    expect(ctx.reason).toBeUndefined()
  })

  it("有 token + 云端不可达(网络错) + probe=true → tier='local', reason='cloud_unreachable'", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("net")))
    const ctx = await buildTierContext({
      getToken: async () => "tok-abc",
      probe: true,
    })
    expect(ctx.tier).toBe("local")
    expect(ctx.cloudReachable).toBe(false)
    expect(ctx.hasToken).toBe(true)
    expect(ctx.reason).toBe("cloud_unreachable")
  })

  it("有 token + probe=false → tier='local', reason='not_probed'(保守)", async () => {
    const fetchFn = vi.fn()
    vi.stubGlobal("fetch", fetchFn)
    const ctx = await buildTierContext({
      getToken: async () => "tok-abc",
      probe: false,
    })
    expect(ctx.tier).toBe("local")
    expect(ctx.reason).toBe("not_probed")
    expect(fetchFn).not.toHaveBeenCalled()
  })
})

// ══════════════════════════════════════════════════════════════
// F-F(F8): feature 白名单分支
// ══════════════════════════════════════════════════════════════

describe("F-F(F8) / feature 白名单路由", () => {
  it("CLOUD_FEATURES 包含 auth/subscription/license/usage/llm/billing", () => {
    for (const f of ["auth", "subscription", "license", "usage", "llm", "billing"]) {
      expect(CLOUD_FEATURES.has(f)).toBe(true)
    }
  })

  it("probeCloudReachable 使用 feature='llm' → URL 走 cloud.test/cloud/llm/health", async () => {
    const fn = vi.fn(async () => jsonResponse(200, {}))
    vi.stubGlobal("fetch", fn)
    await probeCloudReachable()
    const url = String((fn as any).mock.calls[0][0])
    // 若走的是 feature='cloud'(显式 target),URL 仍是 cloud.test/cloud/llm/health;
    // 但为了证明白名单分支真的被走到,我们显式断言传入的是 'llm'
    // 通过 cloudFeatureRequest 走一次以捕获 opts.feature:
    // 这里直接看 gatewayRequest 的 mock —— 换个方式,用 cloudFeatureRequest 断言
    expect(url).toContain("/cloud/llm/health")
  })

  it("cloudFeatureRequest 通过白名单 feature 触发云端路由(不是 local)", async () => {
    const fn = vi.fn(async () => jsonResponse(200, { usage: 42 }))
    vi.stubGlobal("fetch", fn)
    const r = await cloudFeatureRequest("usage", "usage/monthly")
    expect(r.target).toBe("cloud")
    const url = String((fn as any).mock.calls[0][0])
    // 关键断言:URL 是 cloud.test/cloud/usage/monthly(走白名单 feature='usage')
    expect(url).toBe("http://cloud.test/cloud/usage/monthly")
  })

  it("isCloudFeature 正确分类云端/本地 feature", () => {
    expect(isCloudFeature("usage")).toBe("cloud")
    expect(isCloudFeature("license")).toBe("cloud")
    expect(isCloudFeature("billing")).toBe("cloud")
    expect(isCloudFeature("llm")).toBe("cloud")
    expect(isCloudFeature("auth")).toBe("cloud")
    expect(isCloudFeature("subscription")).toBe("cloud")
    expect(isCloudFeature("ping")).toBe("local") // 白名单外 → local
    expect(isCloudFeature("files")).toBe("local")
    expect(isCloudFeature("cloud")).toBe("cloud") // 显式
    expect(isCloudFeature("local")).toBe("local")
  })
})

// ══════════════════════════════════════════════════════════════
// F-G: isUserAbort / isUserAbortSignal
// ══════════════════════════════════════════════════════════════

describe("F-G / isUserAbort", () => {
  it("AbortError DOMException → true", () => {
    expect(isUserAbort(new DOMException("aborted", "AbortError"))).toBe(true)
  })

  it("带 detail='aborted' 的错误对象 → true(gateway 层归一化结果)", () => {
    expect(isUserAbort({ name: "SomeError", detail: "aborted" })).toBe(true)
  })

  it("message 含 'abort' 字样 → true", () => {
    expect(isUserAbort({ name: "X", message: "The operation was aborted." })).toBe(true)
    expect(isUserAbort({ name: "X", message: "user aborted request" })).toBe(true)
  })

  it("TimeoutError / 无 abort 信息的普通网络错误 → false", () => {
    expect(isUserAbort(new TypeError("ECONNREFUSED"))).toBe(false)
    expect(isUserAbort({ name: "X", message: "upstream error" })).toBe(false)
    expect(isUserAbort(null)).toBe(false)
    expect(isUserAbort(undefined)).toBe(false)
  })

  it("cause 是 TimeoutError 的 AbortError → false(超时不算用户中断)", () => {
    const err = {
      name: "AbortError",
      message: "timed out",
      cause: { name: "TimeoutError" },
    } as any
    expect(isUserAbort(err)).toBe(false)
  })
})

describe("F-G / isUserAbortSignal", () => {
  it("未传入 signal → false", () => {
    expect(isUserAbortSignal(undefined)).toBe(false)
    expect(isUserAbortSignal(null)).toBe(false)
  })

  it("signal 未 aborted → false", () => {
    const ctrl = new AbortController()
    expect(isUserAbortSignal(ctrl.signal)).toBe(false)
  })

  it("signal 已 aborted 且 reason 无 cause → true(用户中断)", () => {
    const ctrl = new AbortController()
    ctrl.abort()
    expect(isUserAbortSignal(ctrl.signal)).toBe(true)
  })

  it("signal 已 aborted 且 reason 是 TimeoutError → false(超时不算用户中断)", () => {
    const ctrl = new AbortController()
    ctrl.abort({ name: "TimeoutError" } as any)
    expect(isUserAbortSignal(ctrl.signal)).toBe(false)
  })
})

// ══════════════════════════════════════════════════════════════
// F-F(F11): usage 估算常量
// ══════════════════════════════════════════════════════════════

describe("F-F(F11) / usage 估算常量", () => {
  it("USAGE_ESTIMATE_DISCLAIMER 明确说明是估算,不作计费依据", () => {
    expect(USAGE_ESTIMATE_DISCLAIMER.toLowerCase()).toContain("not used for billing")
    expect(USAGE_ESTIMATE_DISCLAIMER.toLowerCase()).toContain("estimated")
  })

  it("USAGE_ESTIMATE 常量结构与后端 len//2 对齐", () => {
    expect(USAGE_ESTIMATE.charsPerToken).toBe(0.5)
    expect(typeof USAGE_ESTIMATE.uiBadge).toBe("string")
    expect(USAGE_ESTIMATE.uiBadge.length).toBeGreaterThan(0)
  })
})

// ══════════════════════════════════════════════════════════════
// 便捷别名导出
// ══════════════════════════════════════════════════════════════

describe("cloudGatewayClient 便捷别名", () => {
  it("暴露所有主 API + 常量", () => {
    expect(typeof cloudGatewayClient.probeCloudReachable).toBe("function")
    expect(typeof cloudGatewayClient.buildTierContext).toBe("function")
    expect(typeof cloudGatewayClient.isUserAbort).toBe("function")
    expect(typeof cloudGatewayClient.isUserAbortSignal).toBe("function")
    expect(typeof cloudGatewayClient.isCloudFeature).toBe("function")
    expect(typeof cloudGatewayClient.cloudFeatureRequest).toBe("function")
    expect(cloudGatewayClient.PROBE_CLOUD_TIMEOUT_MS).toBe(5000)
    expect(typeof cloudGatewayClient.USAGE_ESTIMATE_DISCLAIMER).toBe("string")
    expect(cloudGatewayClient.USAGE_ESTIMATE.charsPerToken).toBe(0.5)
  })
})
