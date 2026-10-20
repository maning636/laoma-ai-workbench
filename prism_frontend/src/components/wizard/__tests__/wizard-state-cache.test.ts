import { describe, expect, it, beforeEach } from "vitest"
import {
  clearAllSceneDrafts,
  clearSceneDraft,
  getSceneDraft,
  peekSceneDraft,
  setSceneDraft,
  type AiImageDraft,
  type AiWritingDraft,
  type VideoPipelineDraft,
} from "../wizard-state-cache"

describe("wizard-state-cache — getSceneDraft / setSceneDraft", () => {
  beforeEach(() => {
    clearAllSceneDrafts()
  })

  it("未缓存时返回 initial() 结果", () => {
    const draft = getSceneDraft<AiWritingDraft>("x", () => ({
      platformIds: [],
      topic: "",
      titleCandidates: [],
      title: "",
      tags: [],
      body: "",
      published: false,
      publishedAt: 0,
    }))
    expect(draft.platformIds).toEqual([])
    expect(draft.topic).toBe("")
  })

  it("setSceneDraft 后再 get 返回缓存", () => {
    const draft: AiWritingDraft = {
      platformIds: ["douyin", "xhs"],
      topic: "AI 工具",
      titleCandidates: ["A"],
      title: "A",
      tags: ["AI"],
      body: "正文",
      published: false,
      publishedAt: 0,
    }
    setSceneDraft("ai-writing", draft)
    expect(getSceneDraft<AiWritingDraft>("ai-writing", () => draft)).toEqual(draft)
    expect(peekSceneDraft<AiWritingDraft>("ai-writing")).toBe(draft)
  })

  it("clearSceneDraft 使缓存回落到 initial", () => {
    const draft: AiWritingDraft = {
      platformIds: ["douyin"],
      topic: "x",
      titleCandidates: [],
      title: "",
      tags: [],
      body: "",
      published: false,
      publishedAt: 0,
    }
    setSceneDraft("s", draft)
    clearSceneDraft("s")
    const fresh = getSceneDraft<AiImageDraft>(
      "s",
      () => ({
        referencePreview: [],
        agentId: "",
        imageTypeId: "",
        generatedUrls: [],
        generatedTaskId: "",
      }),
    )
    expect(fresh.agentId).toBe("")
    expect(fresh.referencePreview).toEqual([])
  })

  it("clearAllSceneDrafts 清空全部", () => {
    setSceneDraft("a", { foo: 1 })
    setSceneDraft("b", { bar: 2 })
    clearAllSceneDrafts()
    expect(peekSceneDraft("a")).toBeUndefined()
    expect(peekSceneDraft("b")).toBeUndefined()
  })

  it("不同 scene id 隔离", () => {
    setSceneDraft("a", { kind: "a" })
    setSceneDraft("b", { kind: "b" })
    expect(peekSceneDraft("a")).toEqual({ kind: "a" })
    expect(peekSceneDraft("b")).toEqual({ kind: "b" })
  })
})

describe("wizard-state-cache — VideoPipelineDraft 默认 config", () => {
  beforeEach(() => clearAllSceneDrafts())
  it("默认 addSubtitle/addCover/trimSilent=true, 其余 false", () => {
    const draft = getSceneDraft<VideoPipelineDraft>(
      "video-pipeline",
      () => ({
        materials: [],
        config: {
          addSubtitle: true,
          addCover: true,
          addWatermark: false,
          trimSilent: true,
          autoBgm: false,
        },
        taskId: "",
      }),
    )
    expect(draft.config.addSubtitle).toBe(true)
    expect(draft.config.addCover).toBe(true)
    expect(draft.config.trimSilent).toBe(true)
    expect(draft.config.addWatermark).toBe(false)
    expect(draft.config.autoBgm).toBe(false)
  })
})
