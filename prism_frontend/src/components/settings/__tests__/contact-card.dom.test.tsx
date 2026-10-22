// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 交互测试：ContactCard（线下人工充值模式的用户联系入口）。
 *
 * 覆盖：
 *   - 微信号已配置 → 展示微信号 + 复制按钮（点复制写剪贴板）
 *   - 微信号未配置 → 展示「未配置」提示，不露出空号
 *   - 二维码正常 → 渲染 <img>
 *   - 二维码加载失败 → 降级成「二维码图片缺失」文字，**不留破图**
 *   - 群链接存在 → 出现「打开群链接」按钮
 */

// ── mock @/lib/contact ───────────────────────────────
// contact.ts 的值来自构建期 env，测试里用可变 state 模拟不同配置组合
const mocked = vi.hoisted(() => {
  const state = {
    wechatId: "",
    qr: "",
    groupUrl: "",
    notice: "",
  }
  return { state }
})

// 注意：这里必须用 **getter**。`vi.mock` 的工厂函数只在首次导入时执行一次，
// 若直接写 `CONTACT_WECHAT_ID: state.wechatId`，值会在导入瞬间被快照，
// 后续每个用例改 state 都不生效（组件内 `CONTACT_WECHAT_ID.trim()` 读到的一直是空串）。
vi.mock("@/lib/contact", () => ({
  get CONTACT_WECHAT_ID() {
    return mocked.state.wechatId
  },
  get CONTACT_QR() {
    return mocked.state.qr
  },
  get CONTACT_GROUP_URL() {
    return mocked.state.groupUrl
  },
  get CONTACT_NOTICE() {
    return mocked.state.notice
  },
  RECHARGE_GUIDE: "充值与开通请通过微信联系产品方人工办理（线上支付暂未开放）。",
  hasContactWechat: () => mocked.state.wechatId.trim().length > 0,
  hasContactQr: () => mocked.state.qr.trim().length > 0,
}))

import { ContactCard } from "../contact-card"

beforeEach(() => {
  mocked.state.wechatId = ""
  mocked.state.qr = ""
  mocked.state.groupUrl = ""
  mocked.state.notice = ""
})

afterEach(cleanup)

describe("ContactCard — 微信号", () => {
  it("已配置：展示微信号与复制按钮", () => {
    mocked.state.wechatId = "laoma-workbench"
    render(<ContactCard />)
    expect(screen.getByText("laoma-workbench")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /复制/ })).toBeInTheDocument()
  })

  it("未配置：展示提示而不是空号", () => {
    render(<ContactCard />)
    expect(screen.getByText(/微信号尚未配置/)).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /复制/ })).not.toBeInTheDocument()
  })

  it("点击复制把微信号写进剪贴板", async () => {
    mocked.state.wechatId = "laoma-workbench"
    const user = userEvent.setup()
    // 必须在 userEvent.setup() **之后**覆盖 clipboard：
    // setup() 会自己装一套 clipboard stub，先赋值会被它冲掉（spy 永远 0 次调用）。
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    })
    render(<ContactCard />)
    await user.click(screen.getByRole("button", { name: /复制/ }))
    expect(writeText).toHaveBeenCalledWith("laoma-workbench")
  })
})

describe("ContactCard — 微信二维码入口", () => {
  it("配了二维码路径：渲染二维码图片", () => {
    mocked.state.qr = "/wechat-contact-qr.png"
    render(<ContactCard />)
    const img = screen.getByAltText("产品方微信二维码")
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute("src", "/wechat-contact-qr.png")
  })

  it("二维码加载失败：降级为文字提示，不留破图", () => {
    mocked.state.qr = "/wechat-contact-qr.png"
    render(<ContactCard />)
    const img = screen.getByAltText("产品方微信二维码")
    fireEvent.error(img)
    expect(screen.queryByAltText("产品方微信二维码")).not.toBeInTheDocument()
    expect(screen.getByText(/二维码图片缺失/)).toBeInTheDocument()
  })

  it("配了群链接：出现「打开群链接」按钮（与二维码互相独立）", () => {
    mocked.state.groupUrl = "https://example.com/group"
    render(<ContactCard />)
    const link = screen.getByRole("link", { name: /打开群链接/ })
    expect(link).toHaveAttribute("href", "https://example.com/group")
  })

  it("没配群链接：不显示「打开群链接」按钮", () => {
    mocked.state.qr = "/wechat-contact-qr.png"
    render(<ContactCard />)
    expect(screen.queryByRole("link", { name: /打开群链接/ })).not.toBeInTheDocument()
  })

  it("二维码入口完全没配：展示未配置提示", () => {
    render(<ContactCard />)
    expect(screen.getByText(/二维码尚未配置/)).toBeInTheDocument()
  })
})

describe("ContactCard — 附加说明", () => {
  it("配置了 NOTICE 就展示", () => {
    mocked.state.notice = "工作日 9:00-18:00 在线"
    render(<ContactCard />)
    expect(screen.getByText("工作日 9:00-18:00 在线")).toBeInTheDocument()
  })

  it("没配 NOTICE 就不占位置", () => {
    render(<ContactCard />)
    expect(screen.queryByText(/工作日/)).not.toBeInTheDocument()
  })
})
