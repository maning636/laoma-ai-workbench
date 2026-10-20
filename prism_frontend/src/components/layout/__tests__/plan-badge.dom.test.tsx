// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 交互测试：PlanBadge 组件。
 *
 * 覆盖：
 *   - 首次加载显示 loading skeleton
 *   - Community 默认标识 + 3/3/0 配额
 *   - Pro 标识 + 无限/8 配额
 *   - "升级 Pro" / "续费" 按钮
 *   - collapsed 模式下只显示 icon
 *   - 刷新按钮点击
 */

// ── mock cloudAuth / client-gateway ────────────────────
// 使用 vi.hoisted 把 mock 引用提升到顶层，避免 hoisting 报错
const mocked = vi.hoisted(() => {
  const mockGetAccessToken = vi.fn().mockResolvedValue("test-token")
  // gatewayRequest 每次调用都读 state.flagsResponse 的最新值
  const state: { flagsResponse: unknown } = {
    flagsResponse: { plan: "community", flags: {} },
  }
  const mockGatewayRequest = vi.fn(
    async () => ({
      ok: true,
      data: state.flagsResponse,
    }),
  )
  return { mockGetAccessToken, mockGatewayRequest, state }
})

vi.mock("@/lib/cloud-auth", () => ({
  cloudAuth: { getAccessToken: mocked.mockGetAccessToken },
}))

vi.mock("@/lib/client-gateway", () => ({
  // vi.fn 有 variadic 签名，直接引用即可
  gatewayRequest: mocked.mockGatewayRequest,
}))

import { PlanBadge } from "../plan-badge"

beforeEach(() => {
  mocked.mockGetAccessToken.mockClear()
  mocked.mockGetAccessToken.mockResolvedValue("test-token")
  mocked.mockGatewayRequest.mockClear()
  mocked.state.flagsResponse = { plan: "community", flags: {} }
})

afterEach(cleanup)

describe("PlanBadge — Community 默认渲染", () => {
  it("挂载后显示 Community badge、3/3/0 配额与 升级 Pro 按钮", async () => {
    render(<PlanBadge />)
    await waitFor(() => {
      expect(screen.getByText("Community")).toBeInTheDocument()
    })
    // 三个 QuotaCell 显示 3 / 3 / 0（accountsLabel=3, platformsLabel=3, agentLabel=0）
    // Community 下 accounts 和 platforms 都是 3，出现两次
    expect(screen.getAllByText("3")).toHaveLength(2)
    expect(screen.getByText("0")).toBeInTheDocument()
    // 升级按钮
    expect(screen.getByText("升级 Pro")).toBeInTheDocument()
    // 组标签
    expect(
      screen.getByRole("group", { name: /Community/ }),
    ).toBeInTheDocument()
  })

  it("首次加载短暂显示 loading 骨架（aria-busy）", () => {
    // 阻止 async load 完成，让 loading 状态保留
    mocked.mockGatewayRequest.mockReturnValueOnce(new Promise(() => {}))
    const { unmount } = render(<PlanBadge />)
    expect(screen.getByLabelText("加载套餐信息")).toBeInTheDocument()
    unmount()
  })
})

describe("PlanBadge — Pro 用户渲染", () => {
  it("Pro flags 显示 Pro badge、8 平台与 续费 按钮", async () => {
    mocked.state.flagsResponse = {
      plan: "pro",
      flags: {
        max_accounts: -1, // 无限账号 → 显示 Infinity 图标
        max_platforms: 8,
        agent_quota: -1, // 无限智能体 → 显示 Infinity 图标
      },
    }
    render(<PlanBadge />)
    await waitFor(() => {
      expect(screen.getByText("Pro")).toBeInTheDocument()
    })
    // "无限" 通过 lucide InfinityIcon 展示（无文本），此处断言平台数字
    expect(screen.getByText("8")).toBeInTheDocument()
    expect(screen.getByText("续费")).toBeInTheDocument()
    // Pro 徽标组
    expect(
      screen.getByRole("group", { name: /Pro 会员/ }),
    ).toBeInTheDocument()
  })
})

describe("PlanBadge — 升级按钮跳转", () => {
  it("默认升级 URL 为 /settings", async () => {
    render(<PlanBadge />)
    await waitFor(() => screen.getByText("Community"))
    const link = screen.getByRole("link", { name: /升级 Pro/ })
    expect(link).toHaveAttribute("href", "/settings")
  })

  it("upgradeUrl 属性覆盖默认值", async () => {
    render(<PlanBadge upgradeUrl="https://pay.example.com/pro" />)
    await waitFor(() => screen.getByText("Community"))
    const link = screen.getByRole("link", { name: /升级 Pro/ })
    expect(link).toHaveAttribute("href", "https://pay.example.com/pro")
  })
})

describe("PlanBadge — 刷新按钮", () => {
  it("点击刷新按钮触发一次新的 fetch", async () => {
    const user = userEvent.setup()
    render(<PlanBadge />)
    await waitFor(() => screen.getByText("Community"))
    expect(mocked.mockGatewayRequest).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole("button", { name: /刷新套餐/ }))
    await waitFor(() => {
      expect(mocked.mockGatewayRequest).toHaveBeenCalledTimes(2)
    })
  })
})

describe("PlanBadge — collapsed 模式", () => {
  it("collapsed=true 时只显示图标链接（无 quota 数字）", async () => {
    render(<PlanBadge collapsed />)
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /Community/ }),
      ).toBeInTheDocument()
    })
    // collapsed 下不显示 quota 数字
    expect(screen.queryByText("3")).not.toBeInTheDocument()
    expect(screen.queryByText("升级 Pro")).not.toBeInTheDocument()
  })
})

describe("PlanBadge — API 失败兜底", () => {
  it("网关请求失败时回落 Community 显示", async () => {
    // 让 gatewayRequest 抛出
    mocked.mockGetAccessToken.mockRejectedValueOnce(new Error("no-token"))
    mocked.mockGatewayRequest.mockRejectedValueOnce(new Error("network"))
    render(<PlanBadge />)
    await waitFor(() => {
      expect(screen.getByText("Community")).toBeInTheDocument()
    })
  })
})
