import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  ApiError,
  TIMEOUT_ERROR_MESSAGE,
  fetcher,
} from "../api"

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function abortError(): Error {
  // 浏览器/Node 里 AbortError 是 DOMException，jsdom 也支持；这里手动构造一个
  // 只带 name/message 的 Error 走兜底分支，覆盖 fetcher 的字符串判定路径。
  const err = new Error("This operation was aborted")
  err.name = "AbortError"
  return err
}

describe("fetcher — 超时与错误分类", () => {
  it("fetch 因 AbortError 中断时抛 ApiError(408, '请求超时，请稍后重试')", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw abortError()
      })
    )

    await expect(fetcher("http://test.local/x")).rejects.toMatchObject({
      name: "ApiError",
      code: 408,
      message: TIMEOUT_ERROR_MESSAGE,
    })
  })

  it("AbortError 文案包含「超时」关键词", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw abortError()
      })
    )

    try {
      await fetcher("http://test.local/x")
      throw new Error("should have thrown")
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect((err as ApiError).code).toBe(408)
      expect((err as ApiError).message).toContain("超时")
    }
  })

  it("非 Abort 的普通错误仍包装为 ApiError(500)，不覆盖原有语义", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new Error("network down")
      })
    )

    try {
      await fetcher("http://test.local/x")
      throw new Error("should have thrown")
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError)
      expect((err as ApiError).code).toBe(500)
      expect((err as ApiError).message).toBe("network down")
    }
  })
})
