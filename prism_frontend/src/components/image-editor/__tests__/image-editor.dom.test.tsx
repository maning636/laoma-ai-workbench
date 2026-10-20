// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import * as React from "react"

/**
 * DOM 交互测试：ImageEditor 组件。
 *
 * ImageEditor 内部依赖 fabric.Canvas（重 DOM 库）与 react-dropzone、ReactCrop。
 * 为保持测试稳定，mock 掉 fabric 与 image-editor-logic.createBaseCanvas，
 * 以及 react-image-crop 组件，聚焦在 UI 状态与交互。
 *
 * 覆盖：
 *   - 初始上传阶段渲染（拖拽提示 + 文件 input + 4 Tabs）
 *   - 顶部 M5 图片编辑器 标签
 *   - 清空按钮初始 disabled
 *   - 4 个阶段 Tabs 渲染
 *   - 组件在初始状态下不崩溃
 */

// ── mocks ────────────────────────────────────────────
const fakeCanvasInstance = {
  getElement: () => ({ style: {}, appendChild: vi.fn() }),
  on: vi.fn(),
  dispose: vi.fn(),
  add: vi.fn(),
  setActiveObject: vi.fn(),
  renderAll: vi.fn(),
  toJSON: () => ({}),
  getActiveObject: () => null,
  remove: vi.fn(),
  toDataURL: () => "data:image/png;base64,xxx",
  width: 800,
  height: 600,
  set: vi.fn(),
  getHeight: () => 600,
}

vi.mock("fabric", () => ({
  Canvas: class {
    constructor(_el: unknown, _opts: unknown) {
      return fakeCanvasInstance
    }
  },
  Text: class { constructor() {} },
  Rect: class { constructor() {} },
  Circle: class { constructor() {} },
  Triangle: class { constructor() {} },
  Line: class { constructor() {} },
}))

vi.mock("@/lib/image-editor-logic", async () => {
  const actual = await vi.importActual<typeof import("@/lib/image-editor-logic")>(
    "@/lib/image-editor-logic",
  )
  return {
    ...actual,
    createBaseCanvas: vi.fn(async () => fakeCanvasInstance),
  }
})

vi.mock("react-image-crop", () => ({
  default: ({ children }: { children?: React.ReactNode }) => (
    <div data-testid="react-crop-mock">{children}</div>
  ),
}))

import { ImageEditor } from "../image-editor"

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

// ── 测试 ────────────────────────────────────────────

describe("ImageEditor — 上传阶段渲染", () => {
  it("初始状态渲染上传卡片、拖拽提示与 4 个阶段 Tabs", () => {
    render(<ImageEditor />)
    // 上传区标题
    expect(screen.getByText(/上传 \/ 拖拽图片/)).toBeInTheDocument()
    // 提示文本
    expect(screen.getByText(/拖拽图片到这里/)).toBeInTheDocument()
    // 支持格式提示文本（有多处提及）
    expect(screen.getAllByText(/支持 JPG/).length).toBeGreaterThanOrEqual(1)
    // 4 个 Tabs
    expect(screen.getByText(/1\. 上传/)).toBeInTheDocument()
    expect(screen.getByText(/2\. 裁剪/)).toBeInTheDocument()
    expect(screen.getByText(/3\. 编辑/)).toBeInTheDocument()
    expect(screen.getByText(/4\. 导出/)).toBeInTheDocument()
    // 文件 input 存在（hidden 但可用）
    const input = document.querySelector('input[type="file"]')
    expect(input).not.toBeNull()
  })

  it("顶部 M5 图片编辑器 标签显示", () => {
    render(<ImageEditor />)
    expect(screen.getByText("M5")).toBeInTheDocument()
    expect(screen.getByText("图片编辑器")).toBeInTheDocument()
  })
})

describe("ImageEditor — 初始状态禁用状态", () => {
  it("清空按钮在 upload 阶段 disabled", () => {
    render(<ImageEditor />)
    const btn = screen.getByRole("button", { name: /清空/ })
    expect(btn).toBeDisabled()
  })

  it("渲染 4 个阶段 Tabs", () => {
    render(<ImageEditor />)
    const tabs = screen.getAllByText(/^(\d)\. /)
    expect(tabs.length).toBe(4)
  })

  it("初始不显示 应用裁剪 按钮（未进入 crop 阶段）", () => {
    render(<ImageEditor />)
    expect(
      screen.queryByRole("button", { name: /应用裁剪/ }),
    ).not.toBeInTheDocument()
  })

  it("初始不显示 完成编辑 按钮（未进入 edit 阶段）", () => {
    render(<ImageEditor />)
    expect(
      screen.queryByRole("button", { name: /完成编辑/ }),
    ).not.toBeInTheDocument()
  })

  it("初始不显示 下载 PNG 按钮（未进入 export 阶段）", () => {
    render(<ImageEditor />)
    expect(
      screen.queryByRole("button", { name: /下载 PNG/ }),
    ).not.toBeInTheDocument()
  })
})
