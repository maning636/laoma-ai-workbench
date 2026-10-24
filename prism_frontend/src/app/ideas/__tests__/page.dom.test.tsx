// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 测试：IdeasPage「从我的表现生成选题」区块（L3-2）。
 *
 * 覆盖：
 *   - 空态：后端返回 data_ready=false 时展示 hint 原文（用接口 hint 字段）
 *   - 有数据：渲染建议条目（title + note + heat 进度条 / 百分比）
 *   - 交互：点击按钮触发 GET /api/v1/content-library/ideas/from-performance
 *   - 失败：请求非 2xx 时 toast 使用 dedupeKey="ideas-performance-failed"
 *   - 加载态：请求中显示加载文案
 *
 * ⚠️ 口径陷阱：后端返回体是 `{status, result:{suggestions, data_ready, hint}}`，
 * 而不是顶层 `{suggestions, ...}`。字段名 `note`（不是 `reason`），
 * 本组件按后端实际字段实现，见 prism_backend/.../content_library/router.py。
 */

// ── mock use-toast（模块级单例，需 mock 以便断言 dedupeKey） ──
const mocked = vi.hoisted(() => ({
  toast: vi.fn(),
}))

vi.mock("@/components/ui/use-toast", () => ({
  useToast: () => ({ toast: mocked.toast }),
}))

// ── mock fetch（stubGlobal） ───────────────────────────
const mockedFetch = vi.hoisted(() => vi.fn())
vi.stubGlobal("fetch", mockedFetch)

import IdeasPage from "../page"

function jsonRes(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response
}

/**
 * 按 URL 分派 fetch 响应：
 *   /ideas/from-performance  → perfResponse
 *   其他（/ideas 列表）     → listResponse
 */
function stubPerfAndList(
  perfResponse: unknown,
  listResponse: unknown = { result: { ideas: [] } },
) {
  mockedFetch.mockImplementation(async (url: string | URL | Request) => {
    const s = String(url)
    if (s.includes("/ideas/from-performance")) return jsonRes(perfResponse)
    return jsonRes(listResponse)
  })
}

beforeEach(() => {
  mockedFetch.mockReset()
  mocked.toast.mockReset()
  // 兜底：无 stub 时返回空列表，避免组件挂死
  mockedFetch.mockImplementation(async (url: string | URL | Request) => {
    const s = String(url)
    if (s.includes("/ideas/from-performance")) {
      return jsonRes({ result: { suggestions: [], data_ready: false, hint: "" } })
    }
    return jsonRes({ result: { ideas: [] } })
  })
})

afterEach(() => {
  cleanup()
})

describe("IdeasPage — 从我的表现生成选题（L3-2）", () => {
  it("点击生成按钮后调用 /ideas/from-performance 端点", async () => {
    const user = userEvent.setup()
    stubPerfAndList({
      result: { suggestions: [], data_ready: false, hint: "无数据" },
    })
    render(<IdeasPage />)

    // 初始只加载 ideas 列表
    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalledWith(expect.stringContaining("/ideas"), expect.anything())
    })

    // 点击「从我的表现生成」按钮
    await user.click(screen.getByRole("button", { name: /从我的表现生成$/ }))

    await waitFor(() => {
      expect(mockedFetch).toHaveBeenCalledWith(
        expect.stringContaining("/ideas/from-performance"),
        expect.anything(),
      )
    })
  })

  it("data_ready=false 时渲染 hint 原文（接口返回体）", async () => {
    const user = userEvent.setup()
    const hint = "暂无视频回收数据。请先在发布中心完成一次发布并触发数据回收。"
    stubPerfAndList({
      result: { suggestions: [], data_ready: false, hint },
    })
    render(<IdeasPage />)
    await user.click(screen.getByRole("button", { name: /从我的表现生成$/ }))

    await waitFor(() => {
      expect(screen.getByText(hint)).toBeInTheDocument()
    })
  })

  it("有建议时渲染 title / note / heat 进度条（百分比 + progressbar 语义）", async () => {
    const user = userEvent.setup()
    stubPerfAndList({
      result: {
        suggestions: [
          { id: "perf-1", title: "AI 生图爆款拆解", note: "抖音 · 播放 1200 · 点赞 80 · 评论 40 · 收藏 30", heat: 1.0 },
          { id: "perf-2", title: "小红书素人测评", note: "小红书 · 播放 600 · 点赞 45 · 评论 20 · 收藏 15", heat: 0.5 },
        ],
        data_ready: true,
        hint: null,
      },
    })
    render(<IdeasPage />)
    await user.click(screen.getByRole("button", { name: /从我的表现生成$/ }))

    // 两条建议的 title 都渲染
    await waitFor(() => {
      expect(screen.getByText("AI 生图爆款拆解")).toBeInTheDocument()
      expect(screen.getByText("小红书素人测评")).toBeInTheDocument()
    })

    // note 明细渲染
    expect(screen.getByText(/抖音 · 播放 1200/)).toBeInTheDocument()
    expect(screen.getByText(/小红书 · 播放 600/)).toBeInTheDocument()

    // heat 百分比文本 + progressbar 语义（aria-valuenow）
    expect(screen.getByText("100%")).toBeInTheDocument()
    expect(screen.getByText("50%")).toBeInTheDocument()
    expect(screen.getByRole("progressbar", { name: "热度 100%" })).toHaveAttribute("aria-valuenow", "100")
    expect(screen.getByRole("progressbar", { name: "热度 50%" })).toHaveAttribute("aria-valuenow", "50")
  })

  it("接口失败（非 2xx）时 toast 带 dedupeKey=ideas-performance-failed", async () => {
    const user = userEvent.setup()
    mockedFetch.mockImplementation(async (url: string | URL | Request) => {
      const s = String(url)
      if (s.includes("/ideas/from-performance")) {
        return {
          ok: false,
          status: 500,
          json: async () => ({ detail: "upstream error" }),
        } as Response
      }
      return jsonRes({ result: { ideas: [] } })
    })
    render(<IdeasPage />)
    await user.click(screen.getByRole("button", { name: /从我的表现生成$/ }))

    await waitFor(() => {
      expect(mocked.toast).toHaveBeenCalledWith(
        expect.objectContaining({
          variant: "destructive",
          dedupeKey: "ideas-performance-failed",
        }),
      )
    })
  })

  it("生成过程中显示加载态文案（防重复点击）", async () => {
    const user = userEvent.setup()
    // 挂起 fetch，让加载态保持
    mockedFetch.mockImplementation(async (url: string | URL | Request) => {
      const s = String(url)
      if (s.includes("/ideas/from-performance")) return new Promise<Response>(() => {})
      return jsonRes({ result: { ideas: [] } })
    })
    render(<IdeasPage />)
    await user.click(screen.getByRole("button", { name: /从我的表现生成$/ }))

    await waitFor(() => {
      expect(screen.getByText(/正在读取你的视频表现/)).toBeInTheDocument()
    })
    // 按钮在加载期间应被 disabled
    expect(screen.getByRole("button", { name: /从我的表现生成$/ })).toBeDisabled()
  })
})
