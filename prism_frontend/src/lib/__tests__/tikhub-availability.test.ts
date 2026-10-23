import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// Mock env.ts 给一个稳定的 URL 基线,避免依赖 .env
vi.mock("@/lib/env", () => ({
  backendBaseUrl: "http://local.test",
  cloudBaseUrl: "http://cloud.test",
}))

import {
  describeTikHubAvailability,
  probeTikHubAvailability,
  resolveTikHubAvailability,
  shouldHideTikHubEntry,
} from "../tikhub-availability"

describe("resolveTikHubAvailability", () => {
  it("tikhub_enabled:false → unavailable", () => {
    expect(
      resolveTikHubAvailability({ tikhub_enabled: false }).availability,
    ).toBe("unavailable")
  })

  it("tikhub_enabled:true → available", () => {
    expect(
      resolveTikHubAvailability({ tikhub_enabled: true }).availability,
    ).toBe("available")
  })

  it("兼容只有 configured 字段的旧形状", () => {
    expect(resolveTikHubAvailability({ configured: false }).availability).toBe(
      "unavailable",
    )
    expect(resolveTikHubAvailability({ configured: true }).availability).toBe(
      "available",
    )
  })

  it("★ 空对象 → unknown", () => {
    expect(resolveTikHubAvailability({}).availability).toBe("unknown")
  })

  it("★ null / 非对象 → unknown", () => {
    expect(resolveTikHubAvailability(null).availability).toBe("unknown")
    expect(resolveTikHubAvailability("x").availability).toBe("unknown")
  })

  it("★ 字段类型不对 → unknown", () => {
    expect(
      resolveTikHubAvailability({ tikhub_enabled: "false" }).availability,
    ).toBe("unknown")
  })

  it("透传中文 message", () => {
    const r = resolveTikHubAvailability({
      tikhub_enabled: false,
      message: "TikHub 数据接口未配置",
    })
    expect(r.message).toBe("TikHub 数据接口未配置")
  })
})

describe("shouldHideTikHubEntry", () => {
  it("★ 只有 unavailable 才隐藏", () => {
    expect(shouldHideTikHubEntry("unavailable")).toBe(true)
  })

  it("★ unknown 不隐藏(探测失败不能误伤)", () => {
    expect(shouldHideTikHubEntry("unknown")).toBe(false)
  })

  it("available 不隐藏", () => {
    expect(shouldHideTikHubEntry("available")).toBe(false)
  })

  it("null / undefined 不隐藏", () => {
    expect(shouldHideTikHubEntry(null)).toBe(false)
    expect(shouldHideTikHubEntry(undefined)).toBe(false)
  })
})

describe("describeTikHubAvailability", () => {
  it("unavailable → 说明里提到 TikHub 与配置位置", () => {
    const text = describeTikHubAvailability("unavailable")
    expect(text).toContain("TikHub")
  })

  it("unknown → 说明是探测失败", () => {
    expect(describeTikHubAvailability("unknown")).toContain("未知")
  })
})

describe("probeTikHubAvailability", () => {
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

  it("未配置 → unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(200, { tikhub_enabled: false })),
    )
    const r = await probeTikHubAvailability()
    expect(r.availability).toBe("unavailable")
  })

  it("已配置 → available", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse(200, { tikhub_enabled: true })),
    )
    const r = await probeTikHubAvailability()
    expect(r.availability).toBe("available")
  })

  it("★ 网络失败 → unknown", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("boom")))
    const r = await probeTikHubAvailability()
    expect(r.availability).toBe("unknown")
  })

  it("★ 500 → unknown", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse(500, {})))
    const r = await probeTikHubAvailability()
    expect(r.availability).toBe("unknown")
  })

  it("★ 200 非 JSON → unknown", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not json", { status: 200 })),
    )
    const r = await probeTikHubAvailability()
    expect(r.availability).toBe("unknown")
  })

  it("请求打本地后端的 /api/v1/tikhub/health", async () => {
    const captured: string[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        captured.push(String(input))
        return jsonResponse(200, { tikhub_enabled: true })
      }),
    )
    await probeTikHubAvailability()
    expect(captured[0]).toContain("/api/v1/tikhub/health")
  })
})
