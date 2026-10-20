// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { render, screen, cleanup } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 交互测试：ScenarioGrid / ScenarioCard。
 *
 * 覆盖：
 *   - 4 个场景卡片全部渲染
 *   - 场景 title / 步数描述 / 状态标签显示
 *   - 点击「去开始」触发 onStart 回调
 *   - onStart 收到的场景 id 正确
 */

import { ScenarioGrid, ALL_SCENARIOS } from "../scenarios"

afterEach(cleanup)

describe("ScenarioGrid — 4 大场景全部渲染", () => {
  it("ALL_SCENARIOS 导出 4 个场景，且场景网格渲染 4 张卡", () => {
    const onStart = vi.fn()
    render(<ScenarioGrid onStart={onStart} />)

    // 4 个场景 title 都在
    for (const s of ALL_SCENARIOS) {
      expect(screen.getByText(s.title)).toBeInTheDocument()
      // description
      expect(screen.getByText(s.description)).toBeInTheDocument()
      // 步数提示
      expect(
        screen.getByText(`${s.steps.length} 步`),
      ).toBeInTheDocument()
    }
  })

  it("AI 生图场景标注为 已上线", () => {
    render(<ScenarioGrid onStart={vi.fn()} />)
    // AI 生图的 statusLabel 为 "已上线"
    const labels = screen.getAllByText("已上线")
    expect(labels.length).toBeGreaterThanOrEqual(1)
  })
})

describe("ScenarioGrid — 点击「去开始」回调", () => {
  it("点击 AI 写稿卡片 → onStart 收到正确场景", async () => {
    const user = userEvent.setup()
    const onStart = vi.fn()
    render(<ScenarioGrid onStart={onStart} />)

    // 每张卡都有一枚「去开始」按钮，按顺序找到 AI 写稿那张
    const buttons = screen.getAllByRole("button", { name: /去开始/ })
    expect(buttons).toHaveLength(ALL_SCENARIOS.length)

    // 点击第一张（AI 写稿）
    await user.click(buttons[0])
    expect(onStart).toHaveBeenCalledTimes(1)
    expect(onStart.mock.calls[0][0].id).toBe("ai-writing")
    expect(onStart.mock.calls[0][0].title).toBe(ALL_SCENARIOS[0].title)
  })

  it("点击每张卡分别触发不同场景的 onStart", async () => {
    const user = userEvent.setup()
    const onStart = vi.fn()
    render(<ScenarioGrid onStart={onStart} />)

    const buttons = screen.getAllByRole("button", { name: /去开始/ })
    const ids = ALL_SCENARIOS.map((s) => s.id)

    for (let i = 0; i < buttons.length; i++) {
      await user.click(buttons[i])
      expect(onStart.mock.calls[i][0].id).toBe(ids[i])
    }
    expect(onStart).toHaveBeenCalledTimes(buttons.length)
  })
})
