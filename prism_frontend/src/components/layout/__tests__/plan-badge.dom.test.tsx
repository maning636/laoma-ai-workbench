// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 交互测试：PlanBadge 组件。
 *
 * 覆盖：
 *   - 首次加载显示 loading skeleton
 *   - 限制功能版徽标 + 3/3/0 配额（未激活 / 云端未开通）
 *   - 完整版徽标 + 无限账号 / 多平台 / 智能体 2 + 「续费联系」按钮
 *   - 部分开通徽标（Pro 客户但决定性 flag 停在 Community 档）
 *   - "加微信开通" / "续费联系" 按钮
 *   - collapsed 模式下只显示 icon
 *   - 刷新按钮点击
 *
 * ⚠️ 两处口径陷阱（这个文件早先同时踩中，导致长期红着 / 假通过）：
 *
 * 1) **mock 的模块变了**。组件现在直接 `fetch` 本地后端的
 *    `GET /api/v1/license/effective-flags`（2026-10-24 起不再走 client-gateway），
 *    所以必须 mock **全局 fetch**；早先 mock 的 `@/lib/client-gateway`
 *    根本不会被调用 —— Pro 分支从来没被真正执行过，断言全落在 Community 兜底上。
 *
 * 2) **渲染的文案不是 plan 原始值**。徽标渲染的是 `buildEditionLabel()` 的产物：
 *    非 Pro → 「限制功能版」；Pro 且 10 项决定性 flag 全部达 Pro 档 → 「完整版」；
 *    Pro 但仍有 flag 停在 Community 档 → 「部分开通」。
 *    早先断言的是旧文案 "Community" / "Pro"。
 */

// ── mock cloudAuth + 全局 fetch ────────────────────────
// 使用 vi.hoisted 把 mock 引用提升到顶层，避免 hoisting 报错
const mocked = vi.hoisted(() => {
  const mockGetAccessToken = vi.fn().mockResolvedValue("test-token")
  // 组件每次 fetch 都读 state 的最新值
  const state: { flagsResponse: unknown; ok: boolean; reject: boolean } = {
    flagsResponse: { plan: "community", flags: {} },
    ok: true,
    reject: false,
  }
  const mockFetch = vi.fn(async () => {
    if (state.reject) throw new Error("network")
    return {
      ok: state.ok,
      json: async () => state.flagsResponse,
    }
  })
  return { mockGetAccessToken, mockFetch, state }
})

vi.mock("@/lib/cloud-auth", () => ({
  cloudAuth: { getAccessToken: mocked.mockGetAccessToken },
}))

import { PlanBadge } from "../plan-badge"
import { PRO_FLAG_VALUES } from "@/lib/plan-flags"

beforeEach(() => {
  mocked.mockGetAccessToken.mockClear()
  mocked.mockGetAccessToken.mockResolvedValue("test-token")
  mocked.mockFetch.mockClear()
  mocked.state.flagsResponse = { plan: "community", flags: {} }
  mocked.state.ok = true
  mocked.state.reject = false
  vi.stubGlobal("fetch", mocked.mockFetch)
})

afterEach(() => {
  vi.unstubAllGlobals()
  cleanup()
})

describe("PlanBadge — 限制功能版（Community 默认）", () => {
  it("挂载后显示「限制功能版」徽标、3/3/0 配额与 加微信开通 按钮", async () => {
    render(<PlanBadge />)
    await waitFor(() => {
      expect(screen.getByText("限制功能版")).toBeInTheDocument()
    })
    // 三个 QuotaCell 显示 3 / 3 / 0（accountsLabel=3, platformsLabel=3, agentLabel=0）
    // Community 下 accounts 和 platforms 都是 3，出现两次
    expect(screen.getAllByText("3")).toHaveLength(2)
    expect(screen.getByText("0")).toBeInTheDocument()
    // 升级按钮
    expect(screen.getByText("加微信开通")).toBeInTheDocument()
    // 组标签
    expect(
      screen.getByRole("group", { name: /限制功能版/ }),
    ).toBeInTheDocument()
  })

  it("首次加载短暂显示 loading 骨架（aria-busy）", () => {
    // 阻止 async load 完成，让 loading 状态保留
    mocked.mockFetch.mockReturnValueOnce(new Promise(() => {}))
    const { unmount } = render(<PlanBadge />)
    expect(screen.getByLabelText("加载套餐信息")).toBeInTheDocument()
    unmount()
  })
})

describe("PlanBadge — 完整版（Pro 且决定性 flag 全达）", () => {
  it("Pro flags 显示「完整版」徽标、多平台与 续费联系 按钮", async () => {
    mocked.state.flagsResponse = {
      plan: "pro",
      flags: { ...PRO_FLAG_VALUES },
    }
    render(<PlanBadge />)
    await waitFor(() => {
      expect(screen.getByText("完整版")).toBeInTheDocument()
    })
    // "无限" 通过 lucide InfinityIcon 展示（无文本），此处断言平台文案（D5：不写死数量）
    expect(screen.getByText("多")).toBeInTheDocument()
    // agent_quota = 2
    expect(screen.getByText("2")).toBeInTheDocument()
    expect(screen.getByText("续费联系")).toBeInTheDocument()
    // Pro 徽标组
    expect(
      screen.getByRole("group", { name: /完整版/ }),
    ).toBeInTheDocument()
  })
})

describe("PlanBadge — 部分开通（Pro 但 flag 未全达）", () => {
  it("只开到一半时显示「部分开通」，而不是「完整版」", async () => {
    mocked.state.flagsResponse = {
      plan: "pro",
      flags: { ...PRO_FLAG_VALUES, agent_quota: 0, campaign_orchestration: false },
    }
    render(<PlanBadge />)
    await waitFor(() => {
      expect(screen.getByText("部分开通")).toBeInTheDocument()
    })
    expect(screen.queryByText("完整版")).not.toBeInTheDocument()
    expect(screen.getByText("续费联系")).toBeInTheDocument()
  })
})

describe("PlanBadge — 升级按钮跳转", () => {
  it("默认升级 URL 为 /settings#contact", async () => {
    render(<PlanBadge />)
    await waitFor(() => screen.getByText("限制功能版"))
    const link = screen.getByRole("link", { name: /加微信开通/ })
    expect(link).toHaveAttribute("href", "/settings#contact")
  })

  it("upgradeUrl 属性覆盖默认值", async () => {
    render(<PlanBadge upgradeUrl="https://pay.example.com/pro" />)
    await waitFor(() => screen.getByText("限制功能版"))
    const link = screen.getByRole("link", { name: /加微信开通/ })
    expect(link).toHaveAttribute("href", "https://pay.example.com/pro")
  })
})

describe("PlanBadge — 刷新按钮", () => {
  it("点击刷新按钮触发一次新的 fetch", async () => {
    const user = userEvent.setup()
    render(<PlanBadge />)
    await waitFor(() => screen.getByText("限制功能版"))
    expect(mocked.mockFetch).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole("button", { name: /刷新套餐/ }))
    await waitFor(() => {
      expect(mocked.mockFetch).toHaveBeenCalledTimes(2)
    })
  })
})

describe("PlanBadge — collapsed 模式", () => {
  it("collapsed=true 时只显示图标链接（无 quota 数字）", async () => {
    render(<PlanBadge collapsed />)
    await waitFor(() => {
      expect(
        screen.getByRole("link", { name: /限制功能版/ }),
      ).toBeInTheDocument()
    })
    // collapsed 下不显示 quota 数字
    expect(screen.queryByText("3")).not.toBeInTheDocument()
    expect(screen.queryByText("加微信开通")).not.toBeInTheDocument()
  })
})

describe("PlanBadge — API 失败兜底", () => {
  it("fetch 抛错时回落「限制功能版」显示", async () => {
    mocked.state.reject = true
    render(<PlanBadge />)
    await waitFor(() => {
      expect(screen.getByText("限制功能版")).toBeInTheDocument()
    })
  })

  it("后端返回非 2xx 时也回落「限制功能版」", async () => {
    mocked.state.ok = false
    render(<PlanBadge />)
    await waitFor(() => {
      expect(screen.getByText("限制功能版")).toBeInTheDocument()
    })
  })
})
