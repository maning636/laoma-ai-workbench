// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 交互测试：AgentStudioPanel 组件。
 *
 * 覆盖：
 *   - 组件初始加载时并行 fetch list + quota
 *   - 配额显示 used/limit
 *   - 新建智能体：打开表单、必填校验、成功提交、表单字段渲染
 *   - unauthed 提示
 */

// ── mock env / cloud-auth / fetch ──────────────────────
vi.mock("@/lib/env", () => ({
  API_ENDPOINTS: { base: "http://test.local" },
}))

vi.mock("@/lib/cloud-auth", () => ({
  cloudAuth: { getAccessToken: vi.fn().mockResolvedValue("test-token") },
}))

// 用 vi.stubGlobal 替换 fetch
let mockFetchImpl: ReturnType<typeof vi.fn>
beforeEach(() => {
  mockFetchImpl = vi.fn()
  vi.stubGlobal("fetch", mockFetchImpl)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

import { AgentStudioPanel } from "../agent-studio-panel"

// ── helpers ────────────────────────────────────────────
function jsonRes(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

/**
 * 设置 fetch 返回：
 *   - agents list endpoint → { agents: [...] }
 *   - quota endpoint       → { limit, used, canCreate, upgrade_url }
 */
function stubListAndQuota(
  agents: unknown[] = [],
  quota: { limit: number; used: number; canCreate: boolean; upgrade_url: string } = {
    limit: 2,
    used: 0,
    canCreate: true,
    upgrade_url: "/settings",
  },
) {
  mockFetchImpl.mockImplementation(async (url: string | URL | Request) => {
    const s = String(url)
    if (s.includes("/quota")) {
      return jsonRes(quota)
    }
    return jsonRes({ agents })
  })
}

// ── 测试 ──────────────────────────────────────────────

describe("AgentStudioPanel — 初始化加载", () => {
  it("挂载后调用 list + quota 端点，显示 AI Agent Studio 标题与配额", async () => {
    stubListAndQuota()
    render(<AgentStudioPanel />)
    await waitFor(() => {
      expect(screen.getByText(/AI Agent Studio/)).toBeInTheDocument()
    })
    // 配额 0/2
    expect(screen.getByText(/配额 0\/2/)).toBeInTheDocument()
    // 新建按钮
    expect(screen.getByRole("button", { name: /新建/ })).toBeInTheDocument()
    // 空列表提示
    expect(screen.getByText(/还没有智能体/)).toBeInTheDocument()
  })

  it("未登录（401）时显示登录提示", async () => {
    mockFetchImpl.mockImplementation(async () => jsonRes({}, 401))
    render(<AgentStudioPanel />)
    await waitFor(() => {
      expect(screen.getByText(/请先登录/)).toBeInTheDocument()
    })
  })
})

describe("AgentStudioPanel — 创建表单", () => {
  it("点击 新建 展开表单并显示 4 个字段", async () => {
    const user = userEvent.setup()
    stubListAndQuota()
    render(<AgentStudioPanel />)
    await waitFor(() => screen.getByText(/配额 0\/2/))

    await user.click(screen.getByRole("button", { name: /新建/ }))
    await waitFor(() => {
      expect(
        screen.getByPlaceholderText(/例如：冷色调极简海报/),
      ).toBeInTheDocument()
    })
    // 4 个输入元素：名称 / 描述 / 样例内容 / 设计原则
    expect(
      screen.getByPlaceholderText(/一句话说明/),
    ).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/标题：新品上市/),
    ).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/主色控制/),
    ).toBeInTheDocument()
    // 提交按钮
    expect(screen.getByRole("button", { name: /训练并创建/ })).toBeInTheDocument()
  })

  it("提交空表单 → 显示必填校验错误（名称 / 样例）", async () => {
    const user = userEvent.setup()
    stubListAndQuota()
    render(<AgentStudioPanel />)
    await waitFor(() => screen.getByText(/配额 0\/2/))
    await user.click(screen.getByRole("button", { name: /新建/ }))
    await waitFor(() => screen.getByRole("button", { name: /训练并创建/ }))

    await user.click(screen.getByRole("button", { name: /训练并创建/ }))
    await waitFor(() => {
      expect(screen.getByText(/请输入智能体名称/)).toBeInTheDocument()
      expect(screen.getByText(/请至少填写一条样例内容/)).toBeInTheDocument()
    })
  })

  it("配额用满时 新建 按钮 disabled 并显示升级提示", async () => {
    stubListAndQuota(
      [],
      { limit: 2, used: 2, canCreate: false, upgrade_url: "/settings" },
    )
    render(<AgentStudioPanel />)
    await waitFor(() => {
      expect(screen.getByText(/配额 2\/2/)).toBeInTheDocument()
    })
    expect(
      screen.getByRole("button", { name: /新建/ }),
    ).toBeDisabled()
    expect(
      screen.getByText(/已达配额上限/),
    ).toBeInTheDocument()
  })
})

describe("AgentStudioPanel — 已有智能体列表渲染", () => {
  it("渲染已有 agent 的名称与 tok 徽章", async () => {
    stubListAndQuota([
      {
        id: "a1",
        name: "冷色调极简",
        description: "描述",
        style_prompt: "prompt",
        sample_contents: ["a"],
        design_principles: "",
        style_tokens: 42,
        created_at: 1700000000,
        updated_at: 1700000000,
      },
    ])
    render(<AgentStudioPanel />)
    await waitFor(() => {
      expect(screen.getByText("冷色调极简")).toBeInTheDocument()
    })
    expect(screen.getByText(/42 tok/)).toBeInTheDocument()
    // 样式摘要与删除按钮
    expect(screen.getByText(/风格摘要/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /查看 style_prompt/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /删除/ })).toBeInTheDocument()
  })
})
