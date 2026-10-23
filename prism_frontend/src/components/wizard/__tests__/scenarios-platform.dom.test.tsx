// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest"
import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"

/**
 * DOM 交互测试：AI 写稿发布 · 选择目标平台步骤（对齐后端发布通道）。
 *
 * 契约（与后端实查对齐）：
 *   - 后端发布工具（fastapi publish_tools）+ 登录适配器（platforms/）齐备
 *     的平台共 5 个：douyin / kuaishou / bilibili / xhs(xiaohongshu) / channels
 *   - zhihu / toutiao / xigua 后端没有发布工具，前端必须禁用并标注
 *     「暂不支持发布（仅文案风格）」，避免用户选了走到发布会失败
 */

import { AI_WRITING_SCENARIO, PUBLISH_PLATFORMS } from "../scenarios"
import { clearSceneDraft, peekSceneDraft } from "../wizard-state-cache"
import type { AiWritingDraft } from "../wizard-state-cache"

const PUBLISHABLE_IDS = ["douyin", "kuaishou", "bilibili", "xhs", "channels"]
const NON_PUBLISHABLE_IDS = ["zhihu", "toutiao", "xigua"]

function renderPlatformStep() {
  const step = AI_WRITING_SCENARIO.steps[0]!
  // render(ctx) 未用到 ctx 字段，传空对象即可
  return render(<>{step.render({} as Parameters<typeof step.render>[0])}</>)
}

beforeEach(() => {
  clearSceneDraft("ai-writing")
})

afterEach(cleanup)

describe("AI 写稿 · 选择目标平台 — 渲染", () => {
  it("全部 8 平台渲染，可发布平台 5 个、禁用平台 3 个", () => {
    renderPlatformStep()

    for (const p of PUBLISH_PLATFORMS) {
      expect(screen.getByText(p.label)).toBeInTheDocument()
    }
    expect(PUBLISH_PLATFORMS).toHaveLength(8)

    const enabled = PUBLISH_PLATFORMS.filter((p) => p.publishable)
    const disabled = PUBLISH_PLATFORMS.filter((p) => !p.publishable)
    expect(enabled.map((p) => p.id)).toEqual(PUBLISHABLE_IDS)
    expect(disabled.map((p) => p.id)).toEqual(NON_PUBLISHABLE_IDS)

    // 禁用平台按钮 disabled（「暂不支持」提示数量在下方用例单独断言）
    for (const id of NON_PUBLISHABLE_IDS) {
      const label = PUBLISH_PLATFORMS.find((p) => p.id === id)!.label
      const card = screen.getByRole("button", { name: new RegExp(label) })
      expect(card).toBeDisabled()
    }
    // 可发布平台可勾选
    for (const id of PUBLISHABLE_IDS) {
      const label = PUBLISH_PLATFORMS.find((p) => p.id === id)!.label
      expect(screen.getByRole("button", { name: new RegExp(label) })).toBeEnabled()
    }
  })

  it("禁用提示对 3 个平台各出现一次", () => {
    renderPlatformStep()
    expect(screen.getAllByText("暂不支持发布（仅文案风格）")).toHaveLength(3)
  })
})

describe("AI 写稿 · 选择目标平台 — 交互", () => {
  it("可发布平台点击后选中，再次点击取消", async () => {
    const user = userEvent.setup()
    renderPlatformStep()

    const douyin = screen.getByRole("button", { name: /抖音/ })
    await user.click(douyin)
    const draft = peekSceneDraft<AiWritingDraft>("ai-writing")
    expect(draft?.platformIds).toEqual(["douyin"])

    await user.click(douyin)
    expect(peekSceneDraft<AiWritingDraft>("ai-writing")?.platformIds).toEqual([])
  })

  it("禁用平台点击后不被选中", async () => {
    const user = userEvent.setup()
    renderPlatformStep()

    for (const id of NON_PUBLISHABLE_IDS) {
      const label = PUBLISH_PLATFORMS.find((p) => p.id === id)!.label
      const card = screen.getByRole("button", { name: new RegExp(label) })
      expect(card).toBeDisabled()
      await user.click(card)
    }

    const draft = peekSceneDraft<AiWritingDraft>("ai-writing")
    expect(draft?.platformIds ?? []).toEqual([])
  })

  it("多个可发布平台可同时选中", async () => {
    const user = userEvent.setup()
    renderPlatformStep()

    await user.click(screen.getByRole("button", { name: /抖音/ }))
    await user.click(screen.getByRole("button", { name: /小红书/ }))
    await user.click(screen.getByRole("button", { name: /视频号/ }))

    expect(peekSceneDraft<AiWritingDraft>("ai-writing")?.platformIds).toEqual([
      "douyin",
      "xhs",
      "channels",
    ])
  })
})
