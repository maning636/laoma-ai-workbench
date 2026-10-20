// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, waitFor, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import * as React from "react"

/**
 * DOM 交互测试：Wizard 通用组件。
 *
 * 组件依赖：
 *   - `next/navigation` 的 `useSearchParams` / `useRouter`（通过 vi.mock 打桩）
 *   - `./wizard-core` 的 reducer（真实执行，验证状态流转）
 *   - `./url-sync` 的 buildWizardQuery（真实执行）
 *
 * 每个测试用例都提供独立的 useSearchParams / useRouter mock，
 * 通过 render 时传入的初始 URL 控制场景。
 */

// ── 全局 mocks ────────────────────────────────────────────

let mockSearchParams: URLSearchParams
let mockRouterReplace: ReturnType<typeof vi.fn>

beforeEach(() => {
  mockSearchParams = new URLSearchParams("")
  mockRouterReplace = vi.fn()
})

vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
  useRouter: () => ({
    replace: mockRouterReplace,
    refresh: vi.fn(),
    push: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
  }),
}))

import { Wizard, SceneWizardLink } from "../wizard"
import type { WizardStepDefinition } from "../wizard"

afterEach(cleanup)

// ── 工具：构造测试用的 steps ──────────────────────────────

function makeSteps(
  titles: string[],
  renderBody?: (ctx: { index: number }) => React.ReactNode,
): WizardStepDefinition[] {
  return titles.map((title, index) => ({
    title,
    description: `描述-${index}`,
    render: renderBody
      ? (ctx) => renderBody(ctx)
      : () => <div data-testid={`step-${index}-body`}>step-{index}</div>,
  }))
}

// ── 测试 ──────────────────────────────────────────────────

describe("Wizard — 基础渲染", () => {
  it("渲染 title 与所有 Stepper 步骤按钮", () => {
    render(
      <Wizard
        scene="ai-writing"
        title="AI 写稿发布"
        description="测试描述"
        steps={makeSteps(["选择平台", "选题", "生成", "发布"])}
      />,
    )

    // title 出现
    expect(screen.getByText("AI 写稿发布")).toBeInTheDocument()
    // 描述出现
    expect(screen.getByText("测试描述")).toBeInTheDocument()
    // 4 个步骤按钮都在
    expect(screen.getByRole("button", { name: /选择平台/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /选题/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /生成/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /发布/ })).toBeInTheDocument()
    // 首步 body 显示
    expect(screen.getByTestId("step-0-body")).toBeInTheDocument()
    // 步骤计数 badge
    expect(screen.getByText(/步骤 1 \/ 4/)).toBeInTheDocument()
  })

  it("空 steps 时显示 未开始 badge", () => {
    render(<Wizard scene="empty" steps={[]} />)
    expect(screen.getByText("未开始")).toBeInTheDocument()
  })
})

describe("Wizard — 步骤导航", () => {
  it("点击「下一步」推进 step，body 内容变化", async () => {
    const user = userEvent.setup()
    render(
      <Wizard
        scene="ai-writing"
        steps={makeSteps(["步骤1", "步骤2", "步骤3"])}
      />,
    )

    // 首步内容可见
    expect(screen.getByTestId("step-0-body")).toBeInTheDocument()
    expect(screen.queryByTestId("step-1-body")).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /下一步/ }))

    // 推进后
    expect(screen.getByTestId("step-1-body")).toBeInTheDocument()
    expect(screen.queryByTestId("step-0-body")).not.toBeInTheDocument()
    expect(screen.getByText(/步骤 2 \/ 3/)).toBeInTheDocument()
  })

  it("首步「上一步」按钮 disabled", () => {
    render(
      <Wizard scene="ai-writing" steps={makeSteps(["步骤1", "步骤2"])} />,
    )
    const prev = screen.getByRole("button", { name: /上一步/ })
    expect(prev).toBeDisabled()
  })

  it("点击「上一步」回退到前一步", async () => {
    const user = userEvent.setup()
    // 起始 URL 已带 step=1（进入第 2 步）
    mockSearchParams = new URLSearchParams("scene=ai-writing&step=1")
    render(<Wizard scene="ai-writing" steps={makeSteps(["A", "B", "C"])} />)

    expect(screen.getByTestId("step-1-body")).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: /上一步/ }))
    expect(screen.getByTestId("step-0-body")).toBeInTheDocument()
  })

  it("末步「下一步」按钮文本变成「完成」，点击后进入已完成视图", async () => {
    const user = userEvent.setup()
    // 起始 URL 已带 step=2（进入第 3 步 / 末步）
    mockSearchParams = new URLSearchParams("scene=ai-writing&step=2")
    render(<Wizard scene="ai-writing" steps={makeSteps(["A", "B", "C"])} />)

    // 末步文本
    const doneBtn = screen.getByRole("button", { name: /完成/ })
    expect(doneBtn).toBeInTheDocument()

    await user.click(doneBtn)

    // 进入 done 状态：显示"已完成"badge 与"重置"按钮
    expect(screen.getByText("已完成")).toBeInTheDocument()
    expect(screen.getByText("流程已完成")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /重置/ })).toBeInTheDocument()
  })

  it("点击 Stepper 步骤按钮直接跳转", async () => {
    const user = userEvent.setup()
    mockSearchParams = new URLSearchParams("scene=ai-writing")
    render(<Wizard scene="ai-writing" steps={makeSteps(["Alpha", "Beta", "Gamma"])} />)

    // Stepper 按钮的 name 由图标 + 序号 + 标题构成，用精确标题匹配
    const stepperBtn = screen.getByRole("button", { name: /Gamma/ })
    await user.click(stepperBtn)
    expect(screen.getByTestId("step-2-body")).toBeInTheDocument()
    expect(screen.getByText(/步骤 3 \/ 3/)).toBeInTheDocument()
  })
})

describe("Wizard — URL query 同步", () => {
  it("step 变化时通过 router.replace 同步 URL query", async () => {
    const user = userEvent.setup()
    mockSearchParams = new URLSearchParams("scene=ai-writing")
    render(<Wizard scene="ai-writing" steps={makeSteps(["A", "B", "C"])} />)

    await user.click(screen.getByRole("button", { name: /下一步/ }))

    // 至少一次 replace 调用
    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalled()
    })
    const lastCall = mockRouterReplace.mock.calls.at(-1)![0] as string
    // 应包含 step=1
    expect(lastCall).toContain("step=1")
  })

  it("URL 中 step 参数初始值生效", () => {
    mockSearchParams = new URLSearchParams("scene=ai-writing&step=2")
    render(<Wizard scene="ai-writing" steps={makeSteps(["A", "B", "C"])} />)
    // 直接显示第 3 步
    expect(screen.getByTestId("step-2-body")).toBeInTheDocument()
    expect(screen.getByText(/步骤 3 \/ 3/)).toBeInTheDocument()
  })

  it("done=1 时进入已完成视图", () => {
    mockSearchParams = new URLSearchParams("scene=ai-writing&done=1")
    render(<Wizard scene="ai-writing" steps={makeSteps(["A", "B", "C"])} />)
    expect(screen.getByText("流程已完成")).toBeInTheDocument()
  })
})

describe("Wizard — onComplete 与 doneActions", () => {
  it("进入 done 状态时触发 onComplete", async () => {
    const user = userEvent.setup()
    const onComplete = vi.fn()
    mockSearchParams = new URLSearchParams("scene=ai-writing&step=1")
    render(
      <Wizard
        scene="ai-writing"
        steps={makeSteps(["A", "B"])}
        onComplete={onComplete}
      />,
    )
    // 当前末步（step=1 是最后一项），点击完成
    await user.click(screen.getByRole("button", { name: /完成/ }))
    await waitFor(() => {
      expect(onComplete).toHaveBeenCalled()
    })
  })

  it("doneActions 在已完成视图里显示", async () => {
    const user = userEvent.setup()
    mockSearchParams = new URLSearchParams("scene=ai-writing&step=1")
    render(
      <Wizard
        scene="ai-writing"
        steps={makeSteps(["A", "B"])}
        doneActions={<button type="button">去发布</button>}
      />,
    )
    await user.click(screen.getByRole("button", { name: /完成/ }))
    expect(screen.getByRole("button", { name: /去发布/ })).toBeInTheDocument()
  })
})

describe("SceneWizardLink", () => {
  it("自定义 href 生效", () => {
    render(
      <SceneWizardLink scene="ai-writing" href="/test">
        点击进入
      </SceneWizardLink>,
    )
    const link = screen.getByRole("link", { name: /点击进入/ })
    expect(link).toHaveAttribute("href", "/test")
  })

  it("未提供 href 时回落到 /?scene=<id>", () => {
    render(
      <SceneWizardLink scene="ai-writing">
        默认链接
      </SceneWizardLink>,
    )
    const link = screen.getByRole("link", { name: /默认链接/ })
    expect(link).toHaveAttribute("href", "/?scene=ai-writing")
  })
})
