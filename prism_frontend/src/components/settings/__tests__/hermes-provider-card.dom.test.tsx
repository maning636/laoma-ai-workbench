// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, cleanup, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 测试：HermesProviderCard「从供应商导入」apply-to 请求契约。
 *
 * 评审 C1（L3-1 遗留 bug）：原实现发 `body: "{}"` 到 POST /ai/providers/{id}/apply-to/chat，
 * 后端 providers_router.py:477 要求 `model_name` 必填（空则 HTTPException 400），
 * 用户点「导入配置」按钮 100% 失败。修法：body 携带 selectedModel。
 *
 * 本文件专门断言 apply-to 请求体含 model_name 字段，防止回归。
 */

// ── mock env（API_ENDPOINTS.base 用于 URL 拼接） ──────────────────
vi.mock("@/lib/env", () => ({
  API_ENDPOINTS: { base: "http://test.local" },
}))

// ── mock use-toast（避免真实单例在 jsdom 下触发副作用） ────────────
const mockedToast = vi.fn()
vi.mock("@/components/ui/use-toast", () => ({
  useToast: () => ({ toast: mockedToast }),
}))

// ── mock fetch ──────────────────────────────────────────────────────
const mockedFetch = vi.fn()
vi.stubGlobal("fetch", mockedFetch)

import { HermesProviderCard } from "../hermes-provider-card"

function jsonRes(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

/**
 * 按 URL 分派 fetch 响应：
 *   - GET  /agent/config/hermes        → { data: null }（未配置）
 *   - GET  /ai/providers               → { data: [{id, name}] }
 *   - GET  /ai/providers/{id}/models   → { data: { models: [...] } }
 *   - POST /ai/providers/{id}/apply-to/chat → { data: {} }（成功）
 */
function stubProviderFlow(
  providers: { id: number; name: string }[] = [{ id: 42, name: "Test Provider" }],
  models: { id: string; name?: string }[] = [{ id: "gpt-4o" }],
) {
  mockedFetch.mockImplementation(async (url: string | URL | Request) => {
    const s = String(url)
    if (s.includes("/agent/config/hermes")) return jsonRes({ data: null })
    if (s.includes("/ai/providers/") && s.endsWith("/models")) return jsonRes({ data: { models } })
    if (s.includes("/ai/providers") && !s.includes("/apply-to")) return jsonRes({ data: providers })
    if (s.includes("/apply-to/chat")) return jsonRes({ data: {} })
    return jsonRes({})
  })
}

beforeEach(() => {
  mockedFetch.mockReset()
  mockedToast.mockReset()
})

afterEach(() => {
  cleanup()
})

describe("HermesProviderCard — 从供应商导入 apply-to 契约（L3 评审 C1）", () => {
  it("点导入配置按钮时 apply-to 请求体携带 model_name=selectedModel", async () => {
    const user = userEvent.setup()
    stubProviderFlow(
      [{ id: 42, name: "Test Provider" }],
      [{ id: "gpt-4o" }, { id: "claude-sonnet-4-5" }],
    )

    render(<HermesProviderCard />)

    // 展开卡片，点「从供应商导入」
    await waitFor(() => screen.getByText("大语言模型配置"))
    await user.click(screen.getByText("大语言模型配置"))

    // 展开后应出现「从供应商导入」按钮（卡片 Collapsible 展开）
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /从供应商导入/ })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("button", { name: /从供应商导入/ }))

    // 弹窗出现（DialogTitle「从模型供应商导入」）
    await waitFor(() => {
      expect(screen.getByText("从模型供应商导入")).toBeInTheDocument()
    })

    // 弹窗内两个 select 顺序：供应商（index 0）、模型（index 1）。
    // 未用 <label htmlFor> 关联，accessible name 为空，只能按顺序取。
    const dialog = screen.getByRole("dialog")
    const selects = within(dialog).getAllByRole("combobox")
    const providerSelect = selects[0]
    await user.selectOptions(providerSelect, "42")

    // 选择模型 → 触发 apply-to 准备
    await waitFor(() => {
      expect(within(dialog).getAllByRole("combobox")[1]).toBeEnabled()
    })
    const modelSelect = within(dialog).getAllByRole("combobox")[1]
    await user.selectOptions(modelSelect, "gpt-4o")

    // 点导入配置按钮
    await user.click(within(dialog).getByRole("button", { name: /导入配置/ }))

    // 找到 /apply-to/chat 调用
    await waitFor(() => {
      const call = mockedFetch.mock.calls.find((c) => String(c[0]).includes("/apply-to/chat"))
      expect(call).toBeDefined()
    })

    const applyCall = mockedFetch.mock.calls.find((c) => String(c[0]).includes("/apply-to/chat"))!
    const init = applyCall[1] as RequestInit
    expect(init?.method).toBe("POST")
    const body = JSON.parse(init.body as string)
    // 评审 C1 断言：body 必须携带 model_name，且等于选中的模型
    expect(body).toEqual({ model_name: "gpt-4o" })

    // 反向断言：不再是评审指出的字面 "{}"
    expect(init.body as string).not.toBe("{}")
  })

  it("URL 命中 /ai/providers/{id}/apply-to/chat，id 为选中的 provider", async () => {
    const user = userEvent.setup()
    stubProviderFlow(
      [{ id: 7, name: "Test Provider 7" }],
      [{ id: "deepseek-chat" }],
    )

    render(<HermesProviderCard />)

    await waitFor(() => screen.getByText("大语言模型配置"))
    await user.click(screen.getByText("大语言模型配置"))

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /从供应商导入/ })).toBeInTheDocument()
    })
    await user.click(screen.getByRole("button", { name: /从供应商导入/ }))

    const dialog = screen.getByRole("dialog")
    const providerSelect = within(dialog).getAllByRole("combobox")[0]
    await user.selectOptions(providerSelect, "7")

    await waitFor(() => {
      expect(within(dialog).getAllByRole("combobox")[1]).toBeEnabled()
    })
    const modelSelect = within(dialog).getAllByRole("combobox")[1]
    await user.selectOptions(modelSelect, "deepseek-chat")

    await user.click(within(dialog).getByRole("button", { name: /导入配置/ }))

    await waitFor(() => {
      const call = mockedFetch.mock.calls.find((c) => String(c[0]).includes("/apply-to/chat"))
      expect(call).toBeDefined()
    })

    const url = String(
      mockedFetch.mock.calls.find((c) => String(c[0]).includes("/apply-to/chat"))![0],
    )
    // provider id 7 出现在 URL path
    expect(url).toContain("/ai/providers/7/apply-to/chat")
  })
})
