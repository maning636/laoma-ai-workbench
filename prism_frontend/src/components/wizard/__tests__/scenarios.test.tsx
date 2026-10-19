import { describe, expect, it } from "vitest"
import {
  ALL_SCENARIOS,
  AI_IMAGE_SCENARIO,
  AI_WRITING_SCENARIO,
  IMAGE_EDITOR_SCENARIO,
  VIDEO_PIPELINE_SCENARIO,
  getScenarioById,
} from "../scenarios"

describe("scenarios — 4 大场景完备", () => {
  it("暴露 4 个场景，且 id 唯一", () => {
    expect(ALL_SCENARIOS).toHaveLength(4)
    const ids = ALL_SCENARIOS.map((s) => s.id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it("覆盖任务要求的 4 个业务场景", () => {
    const ids = new Set(ALL_SCENARIOS.map((s) => s.id))
    expect(ids).toEqual(
      new Set(["ai-writing", "ai-image", "video-pipeline", "image-editor"]),
    )
  })
})

describe("scenarios — 场景1 AI写稿发布", () => {
  it("包含 4 步：选平台 → 选题 → AI 生成 → 确认发布", () => {
    expect(AI_WRITING_SCENARIO.steps).toHaveLength(4)
    expect(AI_WRITING_SCENARIO.steps.map((s) => s.title)).toEqual([
      "选择目标平台",
      "选题",
      "AI 生成内容",
      "确认并发布",
    ])
  })

  it("每个步骤都有 render 函数", () => {
    for (const step of AI_WRITING_SCENARIO.steps) {
      expect(typeof step.render).toBe("function")
    }
  })

  it("target 指向编排入口 /campaigns", () => {
    expect(AI_WRITING_SCENARIO.target).toBe("/campaigns")
  })
})

describe("scenarios — 场景2 AI生图（骨架）", () => {
  it("包含 5 步：上传原图 → 智能体选择 → 类型 → 生成 → 编辑发布", () => {
    expect(AI_IMAGE_SCENARIO.steps).toHaveLength(5)
    expect(AI_IMAGE_SCENARIO.steps.map((s) => s.title)).toEqual([
      "上传原图",
      "智能体选择（可选）",
      "选择图片类型",
      "生成",
      "编辑 / 发布",
    ])
  })
  it("标记为已上线", () => {
    expect(AI_IMAGE_SCENARIO.statusLabel).toBe("已上线")
  })
  it("target 指向 /fusion/image-studio", () => {
    expect(AI_IMAGE_SCENARIO.target).toBe("/fusion/image-studio")
  })
})

describe("scenarios — 场景3 视频流水线", () => {
  it("3 步：选素材 → 配置 → 生成", () => {
    expect(VIDEO_PIPELINE_SCENARIO.steps).toHaveLength(3)
  })
  it("target 指向 /video-pipeline", () => {
    expect(VIDEO_PIPELINE_SCENARIO.target).toBe("/video-pipeline")
  })
})

describe("scenarios — 场景4 图片编辑", () => {
  it("只有一步（直接进入编辑器）", () => {
    expect(IMAGE_EDITOR_SCENARIO.steps).toHaveLength(1)
  })
  it("target 指向 /tools/image-editor", () => {
    expect(IMAGE_EDITOR_SCENARIO.target).toBe("/tools/image-editor")
  })
})

describe("getScenarioById", () => {
  it("命中返回场景定义", () => {
    const s = getScenarioById("ai-writing")
    expect(s?.title).toBe("AI 写稿发布")
  })
  it("未命中返回 undefined", () => {
    expect(getScenarioById("no-such")).toBeUndefined()
  })
  it("空字符串不命中", () => {
    expect(getScenarioById("")).toBeUndefined()
  })
})
