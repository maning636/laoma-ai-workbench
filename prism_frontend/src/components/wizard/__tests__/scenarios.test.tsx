import { describe, expect, it } from "vitest"
import {
  ALL_SCENARIOS,
  AI_IMAGE_SCENARIO,
  AI_WRITING_SCENARIO,
  IMAGE_EDITOR_SCENARIO,
  PUBLISH_PLATFORMS,
  VIDEO_PIPELINE_SCENARIO,
  getScenarioById,
  mockAiGenerateContent,
  mockAiGenerateImages,
  mockAiSuggestTopics,
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

  it("8 大平台列表齐全（抖音/快手/B站/小红书/视频号/知乎/头条/西瓜）", () => {
    expect(PUBLISH_PLATFORMS).toHaveLength(8)
    const labels = PUBLISH_PLATFORMS.map((p) => p.label)
    expect(labels).toEqual([
      "抖音",
      "快手",
      "B 站",
      "小红书",
      "视频号",
      "知乎",
      "头条",
      "西瓜",
    ])
    const ids = PUBLISH_PLATFORMS.map((p) => p.id)
    expect(new Set(ids).size).toBe(8)
  })
})

describe("scenarios — AI 写稿 Mock 函数", () => {
  it("mockAiSuggestTopics 返回 3 条含关键词的候选", () => {
    const s = mockAiSuggestTopics("职场效率工具推荐")
    expect(s).toHaveLength(3)
    for (const t of s) expect(t).toContain("职场效率工具推荐")
  })

  it("mockAiSuggestTopics 空输入时回落为「内容创作」", () => {
    const s = mockAiSuggestTopics("   ")
    expect(s).toHaveLength(3)
    for (const t of s) expect(t).toContain("内容创作")
  })

  it("mockAiGenerateContent 返回 3 条标题 + 5 个标签 + 含选题的正文", () => {
    const r = mockAiGenerateContent("AI 生图")
    expect(r.titleCandidates).toHaveLength(3)
    for (const t of r.titleCandidates) expect(t).toContain("AI 生图")
    expect(r.tags.length).toBeGreaterThanOrEqual(4)
    expect(r.body).toContain("AI 生图")
  })

  it("mockAiGenerateContent 空选题时仍返回结构", () => {
    const r = mockAiGenerateContent("")
    expect(r.titleCandidates).toHaveLength(3)
    expect(r.body.length).toBeGreaterThan(0)
  })
})

describe("scenarios — AI 生图 Mock 函数", () => {
  it("mockAiGenerateImages 按 count 返回对应数量的 picsum URL", () => {
    const urls = mockAiGenerateImages("cover", 4)
    expect(urls).toHaveLength(4)
    for (const u of urls) {
      expect(u).toMatch(/^https:\/\/picsum\.photos\/seed\/cover-\d+\/512\/512\.jpg$/)
    }
    // 每个 URL 唯一（含 index 后缀）
    expect(new Set(urls).size).toBe(4)
  })

  it("mockAiGenerateImages 默认 count=4", () => {
    expect(mockAiGenerateImages("x")).toHaveLength(4)
  })

  it("mockAiGenerateImages 空 seed 时回落为 'prism'", () => {
    const urls = mockAiGenerateImages("   ", 1)
    expect(urls[0]).toContain("prism-1")
  })

  it("mockAiGenerateImages seed 含中文时被 encodeURIComponent", () => {
    const urls = mockAiGenerateImages("封面图", 1)
    expect(urls[0]).not.toContain("封面图")
    expect(urls[0]).toContain("%")
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
  it("标注为演示流程（未接真实 API）", () => {
    expect(AI_IMAGE_SCENARIO.statusLabel).toBe("演示流程")
  })
  it("target 指向 /fusion/image-studio", () => {
    expect(AI_IMAGE_SCENARIO.target).toBe("/fusion/image-studio")
  })
})

describe("scenarios — 场景3 视频流水线", () => {
  it("3 步：选素材 → 配置 → 生成", () => {
    expect(VIDEO_PIPELINE_SCENARIO.steps).toHaveLength(3)
    expect(VIDEO_PIPELINE_SCENARIO.steps.map((s) => s.title)).toEqual([
      "选择素材",
      "流水线配置",
      "生成",
    ])
    // 每步都有 render
    for (const s of VIDEO_PIPELINE_SCENARIO.steps) {
      expect(typeof s.render).toBe("function")
    }
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
