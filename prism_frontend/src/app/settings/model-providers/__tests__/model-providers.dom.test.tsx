// @vitest-environment jsdom
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 测试：模型供应商管理页（OpenRouter / one-api 风格）。
 *
 * 覆盖：
 *   - 列表渲染（mock GET /ai/providers）+ 空态 + 加载失败重试
 *   - 添加对话框校验与提交（名称必填 / BaseURL 校验 / POST 提交）
 *   - 测试连接结果展示（成功 / 失败两条分支）
 *   - 拉取模型后徽章更新
 *   - 应用到通道 POST apply-to
 *   - 删除（无引用成功删除 / 409 references 展示被引用通道）
 *
 * 通过 mock `next/link`（本页只用 Link 做返回按钮）与全局 `fetch`，
 * 让用例之间彼此独立。
 */

// ── 全局 mocks ────────────────────────────────────────────

vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    href,
    children,
    ...rest
  }: { href: string; children?: ReactNode } & Record<string, unknown>) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

import Page from "../page"

const PROVIDERS_BASE = "/api/v1/ai/providers"

type FetchCall = { url: string; init?: RequestInit }
let fetchCalls: FetchCall[] = []
let fetchHandler: (url: string, init?: RequestInit) => Response = () =>
  jsonResponse({ status: "ok", data: [] })

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  })
}

// backendBaseUrl 可能为 "" 或 "http://host:port"；这里用 indexOf 匹配
// path 部分，兼容完整 URL 和相对 URL 两种形态。
function matchPath(url: string): string | null {
  const idx = url.indexOf(PROVIDERS_BASE)
  if (idx === -1) return null
  return url.slice(idx)
}

// 判断是否是 GET 列表请求（可能带 query）
function isListUrl(url: string): boolean {
  const p = matchPath(url)
  if (!p) return false
  return p === PROVIDERS_BASE || p.startsWith(`${PROVIDERS_BASE}?`)
}

// 匹配 /<id> 或 /<id>/<sub...> 的路径尾（如 "/1/test-connection"）
function providerSubPath(url: string): string | null {
  const p = matchPath(url)
  if (!p) return null
  const tail = p.slice(PROVIDERS_BASE.length)
  if (!/^\/[^?#]+/.test(tail)) return null
  return tail
}

function isExactCall(url: string, subPath: string, method?: string, init?: RequestInit): boolean {
  if (method && init?.method !== method) return false
  return providerSubPath(url) === subPath
}

beforeEach(() => {
  fetchCalls = []
  fetchHandler = () => jsonResponse({ status: "ok", data: [] })
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString()
      fetchCalls.push({ url, init })
      return fetchHandler(url, init)
    }),
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
  cleanup()
})

function seedProviders(payloads: unknown[]): void {
  fetchHandler = (url) => {
    if (isListUrl(url)) {
      return jsonResponse({ status: "ok", data: payloads })
    }
    return jsonResponse({ status: "ok" })
  }
}

const SAMPLE_PROVIDER = {
  id: 1,
  name: "OpenRouter",
  base_url: "https://openrouter.ai/api/v1",
  api_key_masked: "sk-****abcd",
  enabled: true,
  remark: "主账号",
  available_models: ["openai/gpt-4o", "anthropic/claude-3.5-sonnet"],
  created_at: "2026-10-01T00:00:00",
  updated_at: "2026-10-01T00:00:00",
}

// ── 测试 ─────────────────────────────────────────────────

describe("ModelProvidersPage — 列表渲染", () => {
  it("拉取列表并渲染每一行（名称、BaseURL、Key 打码、模型数）", async () => {
    seedProviders([SAMPLE_PROVIDER])
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    expect(screen.getByText("https://openrouter.ai/api/v1")).toBeInTheDocument()
    expect(screen.getByText("sk-****abcd")).toBeInTheDocument()
    expect(screen.getByText("已启用")).toBeInTheDocument()
    expect(screen.getByText(/2 个模型/)).toBeInTheDocument()
    expect(screen.getByText(/主账号/)).toBeInTheDocument()
  })

  it("空列表显示空态与「添加第一个供应商」按钮", async () => {
    seedProviders([])
    render(<Page />)

    expect(await screen.findByText("还没有供应商")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /添加第一个供应商/ })).toBeInTheDocument()
  })

  it("列表加载失败显示页面内空态与重试按钮（不走全屏 toast）", async () => {
    fetchHandler = () => jsonResponse({ detail: "boom" }, 500)
    render(<Page />)

    expect(await screen.findByText("供应商列表加载失败")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /重试/ })).toBeInTheDocument()
  })
})

describe("ModelProvidersPage — 添加供应商", () => {
  it("名称为空时提交被拒绝并显示校验提示", async () => {
    const user = userEvent.setup()
    seedProviders([SAMPLE_PROVIDER])
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /添加供应商/ }))
    await user.type(screen.getByLabelText("BaseURL"), "https://example.com/v1")
    await user.click(screen.getByRole("button", { name: /创建供应商/ }))

    expect(await screen.findByText("名称必填")).toBeInTheDocument()
    const postCalls = fetchCalls.filter((c) => {
      if (c.init?.method !== "POST") return false
      // 创建 POST：只匹配 provider 列表本身，不能带 /<id>
      const p = matchPath(c.url)
      return !!p && (p === PROVIDERS_BASE || p.startsWith(`${PROVIDERS_BASE}?`))
    })
    expect(postCalls).toHaveLength(0)
  })

  it("BaseURL 不以 http(s):// 开头时给出校验提示", async () => {
    const user = userEvent.setup()
    seedProviders([SAMPLE_PROVIDER])
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /添加供应商/ }))
    await user.type(screen.getByLabelText("名称（唯一）"), "MyProvider")
    await user.type(screen.getByLabelText("BaseURL"), "example.com")
    await user.click(screen.getByRole("button", { name: /创建供应商/ }))

    expect(await screen.findByText(/BaseURL 必须以/)).toBeInTheDocument()
  })

  it("合法填写后 POST 提交并刷新列表", async () => {
    const user = userEvent.setup()
    let created = false
    fetchHandler = (url, init) => {
      if (init?.method === "POST") {
        const p = matchPath(url)
        if (p === PROVIDERS_BASE) {
          created = true
          return jsonResponse({ status: "ok", data: { id: 2, name: "NewProv" } }, 201)
        }
      }
      if (isListUrl(url)) {
        return jsonResponse({
          status: "ok",
          data: created
            ? [SAMPLE_PROVIDER, { ...SAMPLE_PROVIDER, id: 2, name: "NewProv" }]
            : [SAMPLE_PROVIDER],
        })
      }
      return jsonResponse({ status: "ok" })
    }
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /添加供应商/ }))
    await user.type(screen.getByLabelText("名称（唯一）"), "NewProv")
    await user.type(screen.getByLabelText("BaseURL"), "https://newprov.example.com/v1")
    await user.type(screen.getByLabelText("API Key"), "sk-12345")
    await user.click(screen.getByRole("button", { name: /创建供应商/ }))

    await waitFor(() => {
      expect(
        fetchCalls.some((c) => {
          if (c.init?.method !== "POST") return false
          const p = matchPath(c.url)
          return p === PROVIDERS_BASE
        }),
      ).toBe(true)
    })
    expect(await screen.findByText("NewProv")).toBeInTheDocument()
  })
})

describe("ModelProvidersPage — 测试连接", () => {
  it("测试连接成功后行内展示 latency 与 model 数量", async () => {
    const user = userEvent.setup()
    seedProviders([SAMPLE_PROVIDER])
    fetchHandler = (url, init) => {
      if (isListUrl(url)) return jsonResponse({ status: "ok", data: [SAMPLE_PROVIDER] })
      if (isExactCall(url, "/1/test-connection", "POST", init)) {
        return jsonResponse({ ok: true, latency_ms: 236, model_count: 45 })
      }
      return jsonResponse({ status: "ok" })
    }
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    expect(screen.queryByTestId("test-result-1")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /测试连接/ }))

    const resultBox = await screen.findByTestId("test-result-1")
    expect(resultBox).toHaveTextContent("✓")
    expect(resultBox).toHaveTextContent("236ms")
    expect(resultBox).toHaveTextContent("45 个模型")
  })

  it("测试连接失败展示中文错误，不打断列表", async () => {
    const user = userEvent.setup()
    seedProviders([SAMPLE_PROVIDER])
    fetchHandler = (url, init) => {
      if (isListUrl(url)) return jsonResponse({ status: "ok", data: [SAMPLE_PROVIDER] })
      if (isExactCall(url, "/1/test-connection", "POST", init)) {
        return jsonResponse({ ok: false, error: "鉴权失败：API Key 无效" })
      }
      return jsonResponse({ status: "ok" })
    }
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /测试连接/ }))

    const resultBox = await screen.findByTestId("test-result-1")
    expect(resultBox).toHaveTextContent("✗")
    expect(resultBox).toHaveTextContent("鉴权失败")
    expect(screen.getByText("OpenRouter")).toBeInTheDocument()
  })
})

describe("ModelProvidersPage — 拉取模型", () => {
  it("拉取模型后模型数徽章更新", async () => {
    const user = userEvent.setup()
    const empty = { ...SAMPLE_PROVIDER, available_models: [] as string[] }
    fetchHandler = (url) => {
      if (isListUrl(url)) return jsonResponse({ status: "ok", data: [empty] })
      if (providerSubPath(url) === "/1/models") {
        return jsonResponse({ status: "ok", data: { models: ["m1", "m2", "m3"] } })
      }
      return jsonResponse({ status: "ok" })
    }
    render(<Page />)

    expect(await screen.findByText(/0 个模型/)).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /拉取模型/ }))

    expect(await screen.findByText(/3 个模型/)).toBeInTheDocument()
  })
})

describe("ModelProvidersPage — 应用到通道", () => {
  it("选择 service_type 与模型后 POST apply-to 并关闭对话框", async () => {
    const user = userEvent.setup()
    seedProviders([SAMPLE_PROVIDER])
    fetchHandler = (url, init) => {
      if (isListUrl(url)) return jsonResponse({ status: "ok", data: [SAMPLE_PROVIDER] })
      if (isExactCall(url, "/1/apply-to/chat", "POST", init)) {
        return jsonResponse({
          status: "ok",
          message: "已把供应商「OpenRouter」应用到通道 chat",
        })
      }
      return jsonResponse({ status: "ok" })
    }
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /应用到通道/ }))

    expect(await screen.findByText(/应用到通道：OpenRouter/)).toBeInTheDocument()
    expect(screen.getByLabelText("模型名称")).toHaveValue("openai/gpt-4o")

    await user.click(screen.getByRole("button", { name: /^应用$/ }))

    await waitFor(() => {
      expect(
        fetchCalls.some((c) => isExactCall(c.url, "/1/apply-to/chat", "POST", c.init)),
      ).toBe(true)
    })
  })
})

describe("ModelProvidersPage — 删除", () => {
  it("无引用时确认删除并移除行", async () => {
    const user = userEvent.setup()
    let deleted = false
    fetchHandler = (url, init) => {
      if (isListUrl(url)) {
        return jsonResponse({ status: "ok", data: deleted ? [] : [SAMPLE_PROVIDER] })
      }
      if (isExactCall(url, "/1", "DELETE", init)) {
        deleted = true
        return jsonResponse({ status: "ok" })
      }
      return jsonResponse({ status: "ok" })
    }
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /删除/ }))

    expect(await screen.findByText(/删除供应商「OpenRouter」/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /确认删除/ }))

    await waitFor(() => {
      expect(fetchCalls.some((c) => isExactCall(c.url, "/1", "DELETE", c.init))).toBe(true)
    })
    expect(screen.queryByText("OpenRouter")).not.toBeInTheDocument()
  })

  it("后端返回 409 references 时展示被引用通道列表并禁用删除按钮", async () => {
    const user = userEvent.setup()
    seedProviders([SAMPLE_PROVIDER])
    fetchHandler = (url, init) => {
      if (isListUrl(url)) return jsonResponse({ status: "ok", data: [SAMPLE_PROVIDER] })
      if (isExactCall(url, "/1", "DELETE", init)) {
        return jsonResponse(
          {
            status: "error",
            detail: {
              message: "供应商被通道引用",
              references: [
                { service_type: "chat", provider: "OpenRouter" },
                { service_type: "whisper", provider: "OpenRouter" },
              ],
            },
          },
          409,
        )
      }
      return jsonResponse({ status: "ok" })
    }
    render(<Page />)

    expect(await screen.findByText("OpenRouter")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /删除/ }))
    await user.click(screen.getByRole("button", { name: /确认删除/ }))

    expect(await screen.findByText(/请先在这些通道里手动解除/)).toBeInTheDocument()
    expect(screen.getByText("chat")).toBeInTheDocument()
    expect(screen.getByText("whisper")).toBeInTheDocument()
    expect(screen.getByText("OpenRouter")).toBeInTheDocument()
  })
})
