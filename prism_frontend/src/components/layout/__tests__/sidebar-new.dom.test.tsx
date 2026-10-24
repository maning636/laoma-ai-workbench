// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"

/**
 * DOM 测试：SidebarNew 导航折叠。
 *
 * 覆盖：
 *   - /dashboard-demo（「演示控制台」）与 /guide（「快速开始」）不渲染到侧边栏
 *   - 其它原生入口仍然完整渲染（回归保护：折叠只影响可见性）
 *   - 折叠态与展开态两种 collapsed 场景下都不显示被隐藏的入口
 *
 * 只折叠入口，不删路由：/dashboard-demo 与 /guide 的页面文件保留，
 * 只从 navSections 数组里通过 visible: false 排除渲染。
 */

// next/navigation 是 client runtime API，jsdom 下需 stub
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}))

// framer-motion 的 motion.div 会把 initial / animate / transition / exit 等
// 作为 React props 透传（浏览器上不进入 DOM），jsdom 下会报「Received `false`
// for a non-boolean attribute `initial`」。mock 里只保留原生元素需要的 props。
const KEEP_PROPS = new Set(["children", "className", "style", "role", "aria-label"])

vi.mock("framer-motion", async () => {
  const React = await import("react")
  const passthrough = (Tag: "div" | "aside" | "span") =>
    function Motion({ ...props }: Record<string, unknown>) {
      const clean: Record<string, unknown> = {}
      for (const k of KEEP_PROPS) if (k in props) clean[k] = props[k]
      return React.createElement(Tag, clean as Record<string, unknown>)
    }
  return {
    AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    motion: {
      aside: passthrough("aside"),
      div: passthrough("div"),
      span: passthrough("span"),
    },
  }
})

import { SidebarNew } from "../sidebar-new"

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe("SidebarNew — 导航折叠（L3-2）", () => {
  it("展开态不渲染 /dashboard-demo 与 /guide 入口", async () => {
    render(<SidebarNew collapsed={false} setCollapsed={() => {}} />)

    // 两项被隐藏：href 与 label 都不应出现
    expect(screen.queryByRole("link", { name: /演示控制台/ })).not.toBeInTheDocument()
    expect(screen.queryByRole("link", { name: /快速开始/ })).not.toBeInTheDocument()

    // 反向断言：href 属性也不存在（防御文本改写的回归）
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href]"))
    const hrefs = links.map((a) => a.getAttribute("href"))
    expect(hrefs).not.toContain("/dashboard-demo")
    expect(hrefs).not.toContain("/guide")
  })

  it("折叠态（collapsed=true）下被隐藏的入口依旧不显示", async () => {
    render(<SidebarNew collapsed setCollapsed={() => {}} />)

    // collapsed 走 TooltipProvider + TooltipTrigger；用 href 兜底断言
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>("a[href]"))
    const hrefs = links.map((a) => a.getAttribute("href"))
    expect(hrefs).not.toContain("/dashboard-demo")
    expect(hrefs).not.toContain("/guide")
  })

  it("其它原生入口保留：仪表盘 / 选题库 / 数据中心 等仍在", async () => {
    render(<SidebarNew collapsed={false} setCollapsed={() => {}} />)

    // 覆盖 navSections 各组的关键入口，避免折叠逻辑误伤
    for (const name of ["仪表盘", "选题库", "数据中心", "系统设置", "任务管理"]) {
      expect(screen.getByRole("link", { name })).toBeInTheDocument()
    }

    // 首页锚定断言（防 navSections 结构被误改）
    const homeLink = screen.getByRole("link", { name: "仪表盘" })
    expect(homeLink).toHaveAttribute("href", "/")
  })
})
