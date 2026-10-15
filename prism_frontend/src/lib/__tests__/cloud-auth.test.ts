import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// ──────────────────────────────────────────────────────────────
// F-D: license 离线误判策略测试。
//
// 覆盖点:
//   1. 网络失败(transport)→ 在 grace 窗口内 → 仍视为有效
//   2. grace 窗口过期     → 降级为 cloud_unreachable 失效
//   3. HTTP 401 业务拒绝  → 立即失效
//   4. HTTP 403 / 402     → 立即失效
//   5. HTTP 2xx 成功      → 刷新乐观缓存
//   6. classifyVerifyResult 语义分类
// ──────────────────────────────────────────────────────────────

// 用 vi.mock 固定底层 gateway 的 env URL,便于 URL 断言
vi.mock("@/lib/env", () => ({
  backendBaseUrl: "http://local.test",
  cloudBaseUrl: "http://cloud.test",
}))

// node 环境下没有 window / localStorage,构造最小 polyfill。
// cloud-auth.ts 内部用 window.localStorage 兜底(非 Electron 场景)。
class MemLocalStorage {
  private store = new Map<string, string>()
  getItem(k: string): string | null {
    return this.store.has(k) ? this.store.get(k)! : null
  }
  setItem(k: string, v: string): void {
    this.store.set(k, String(v))
  }
  removeItem(k: string): void {
    this.store.delete(k)
  }
  clear(): void {
    this.store.clear()
  }
}

beforeEach(() => {
  vi.unstubAllGlobals()
  const ls = new MemLocalStorage()
  vi.stubGlobal("window", { localStorage: ls })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

import {
  cloudAuth,
  classifyVerifyResult,
  LICENSE_OFFLINE_GRACE_MS,
  _internal,
} from "../cloud-auth"

/** 直接写一个 token pair 到 localStorage,避开 login/refresh 流程。 */
function seedTokenPair(accessToken: string, refreshToken = "rf-xyz"): void {
  const obtainedAt = Math.floor(Date.now() / 1000)
  const expiresIn = 3600
  window.localStorage.setItem("prism_cloud_access_token", accessToken)
  window.localStorage.setItem("prism_cloud_refresh_token", refreshToken)
  window.localStorage.setItem("prism_cloud_obtained_at", String(obtainedAt))
  window.localStorage.setItem("prism_cloud_expires_in", String(expiresIn))
}

function jsonResponse(status: number, body: unknown = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

describe("classifyVerifyResult / 结果分类", () => {
  it("2xx → ok", () => {
    expect(classifyVerifyResult({ ok: true, status: 200 })).toBe("ok")
  })
  it("status=0 / code='network' → transport", () => {
    expect(classifyVerifyResult({ ok: false, status: 0, code: "network" })).toBe("transport")
  })
  it("5xx → transport(服务端异常,不代表订阅本身)", () => {
    expect(classifyVerifyResult({ ok: false, status: 500 })).toBe("transport")
    expect(classifyVerifyResult({ ok: false, status: 503 })).toBe("transport")
  })
  it("401 / 403 / 402 → business(明确业务拒绝)", () => {
    expect(classifyVerifyResult({ ok: false, status: 401 })).toBe("business")
    expect(classifyVerifyResult({ ok: false, status: 403 })).toBe("business")
    expect(classifyVerifyResult({ ok: false, status: 402 })).toBe("business")
  })
  it("其他 4xx(400/404/422)→ transport(不匹配业务拒绝语义,保守不降级)", () => {
    expect(classifyVerifyResult({ ok: false, status: 400 })).toBe("transport")
    expect(classifyVerifyResult({ ok: false, status: 404 })).toBe("transport")
  })
})

describe("verifyLicense / F-D 乐观降级", () => {
  // 用一个 fake "now" 便于精确控制窗口边界
  const T0 = 1_700_000_000_000

  it("窗口内网络失败 → 保留上次有效的订阅状态", async () => {
    // 1) 先让云端成功返回一次,写入乐观缓存
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      valid: true,
      reason: "ok",
      plan: "pro",
      status: "active",
      expire_at: "2027-01-01",
      quota: 100,
      used: 10,
      remaining: 90,
      is_pro: true,
    })))

    seedTokenPair("tok-abc")
    const r1 = await cloudAuth.verifyLicense({ now: T0 })
    expect(r1.valid).toBe(true)
    expect(r1.plan).toBe("pro")

    // 2) 之后云端网络失败(fetch 抛错)—— 在 T0 + 5min(窗口 10min 内)
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))
    const r2 = await cloudAuth.verifyLicense({ now: T0 + 5 * 60 * 1000 })
    // 关键断言:仍然 valid,保留了上次状态
    expect(r2.valid).toBe(true)
    expect(r2.plan).toBe("pro")
    expect(r2.is_pro).toBe(true)
  })

  it("窗口过期后的网络失败 → 降级为 cloud_unreachable 失效", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      valid: true,
      reason: "ok",
      plan: "pro",
      status: "active",
      expire_at: "2027-01-01",
      quota: 100,
      used: 10,
      remaining: 90,
      is_pro: true,
    })))
    seedTokenPair("tok-abc")
    await cloudAuth.verifyLicense({ now: T0 })

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("ECONNREFUSED")))
    // 走过窗口(10min + 1ms)
    const r = await cloudAuth.verifyLicense({ now: T0 + LICENSE_OFFLINE_GRACE_MS + 1 })
    expect(r.valid).toBe(false)
    expect(r.reason).toBe("cloud_unreachable")
  })

  it("HTTP 500 在窗口内也按 transport 处理(保留有效)", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      valid: true, reason: "ok", plan: "pro", status: "active",
      expire_at: null, quota: 10, used: 1, remaining: 9, is_pro: true,
    })))
    seedTokenPair("tok-abc")
    await cloudAuth.verifyLicense({ now: T0 })

    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(503, { detail: "upstream down" })))
    const r = await cloudAuth.verifyLicense({ now: T0 + 60 * 1000 })
    expect(r.valid).toBe(true)
    expect(r.plan).toBe("pro")
  })

  it("HTTP 401 → 立即失效,即使此前有缓存", async () => {
    // 先缓存一个有效状态
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      valid: true, reason: "ok", plan: "pro", status: "active",
      expire_at: null, quota: 10, used: 1, remaining: 9, is_pro: true,
    })))
    seedTokenPair("tok-abc")
    await cloudAuth.verifyLicense({ now: T0 })

    // 401
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(401, { detail: "token expired" })))
    const r = await cloudAuth.verifyLicense({ now: T0 + 1 })
    expect(r.valid).toBe(false)
    expect(r.reason).toBe("unauthenticated")
    // token 也应被清掉
    expect(window.localStorage.getItem("prism_cloud_access_token")).toBeNull()
  })

  it("HTTP 403 → 立即失效(业务拒绝,不受窗口保护)", async () => {
    seedTokenPair("tok-abc")
    // 没跑过 verifyLicense 前置,直接 403
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(403, { detail: "subscription not active" })))
    const r = await cloudAuth.verifyLicense({ now: T0 })
    expect(r.valid).toBe(false)
    expect(r.reason).toBe("subscription not active")
  })

  it("HTTP 402 → 立即失效(订阅额度用尽)", async () => {
    seedTokenPair("tok-abc")
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(402, { detail: "quota exceeded" })))
    const r = await cloudAuth.verifyLicense({ now: T0 })
    expect(r.valid).toBe(false)
    // 402 不触发 logout,但会返回业务拒绝语义
    expect(r.reason).toBe("quota exceeded")
    expect(window.localStorage.getItem("prism_cloud_access_token")).toBe("tok-abc")
  })

  it("未登录(无 token)→ unauthenticated,不走乐观缓存", async () => {
    // 不 seed token,直接调
    const r = await cloudAuth.verifyLicense({ now: T0 })
    expect(r.valid).toBe(false)
    expect(r.reason).toBe("unauthenticated")
  })

  it("自定义 graceMs 生效", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(200, {
      valid: true, reason: "ok", plan: "pro", status: "active",
      expire_at: null, quota: 10, used: 1, remaining: 9, is_pro: true,
    })))
    seedTokenPair("tok-abc")
    await cloudAuth.verifyLicense({ now: T0 })

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("net")))
    // 自定义窗口 60s:60.5s 后过期
    const r = await cloudAuth.verifyLicense({
      now: T0 + 60_500,
      graceMs: 60_000,
    })
    expect(r.valid).toBe(false)
  })
})

// _internal 目前不导出重置缓存的钩子,但 verifyLicense 的每次成功调用
// 都会覆盖缓存;这里不需要显式清缓存。
// 保留 _internal 引用以避免 tree-shake 警告。
void _internal
