import { describe, expect, it } from "vitest"
import {
  ACCEPTED_IMAGE_TYPES,
  AI_IMAGE_UNIT_POINTS,
  ASPECT_RATIOS,
  EMPTY_DRAFT,
  IMAGE_TYPES,
  MAX_COUNT_PER_REQUEST,
  MAX_REFERENCE_IMAGES,
  NO_AGENT_VALUE,
  buildEditorUrl,
  buildGeneratePayload,
  clampCount,
  deriveLimits,
  estimatePoints,
  filterAcceptedFiles,
  findModel,
  imageTypeHint,
  isAcceptedImage,
  makeIdempotencyKey,
  normalizeAspectRatio,
  normalizeRecord,
  validateDraft,
  type AiDesignModel,
  type ImageStudioDraft,
} from "../image-studio"

describe("constants — 与澜途 PRD & M1 后端一致", () => {
  it("MAX_COUNT_PER_REQUEST = 10", () => {
    expect(MAX_COUNT_PER_REQUEST).toBe(10)
  })
  it("AI_IMAGE_UNIT_POINTS = 1.5（澜途 AI 设计中心 1.5/张）", () => {
    expect(AI_IMAGE_UNIT_POINTS).toBe(1.5)
  })
  it("MAX_REFERENCE_IMAGES = 7（澜途 PRD）", () => {
    expect(MAX_REFERENCE_IMAGES).toBe(7)
  })
  it("ACCEPTED_IMAGE_TYPES 覆盖 JPG/PNG/WebP", () => {
    expect(ACCEPTED_IMAGE_TYPES).toContain("image/jpeg")
    expect(ACCEPTED_IMAGE_TYPES).toContain("image/png")
    expect(ACCEPTED_IMAGE_TYPES).toContain("image/webp")
  })
  it("ASPECT_RATIOS 覆盖澜途 §3.1 常见比例", () => {
    expect(ASPECT_RATIOS).toContain("1:1")
    expect(ASPECT_RATIOS).toContain("16:9")
    expect(ASPECT_RATIOS).toContain("9:16")
    expect(ASPECT_RATIOS).toContain("3:4")
    expect(ASPECT_RATIOS).toContain("4:3")
  })
  it("IMAGE_TYPES 至少 4 个（封面/配图/海报/白底）", () => {
    expect(IMAGE_TYPES.length).toBeGreaterThanOrEqual(4)
    const ids = IMAGE_TYPES.map((t) => t.id)
    expect(ids).toEqual(["cover", "illustration", "poster", "white-bg"])
  })
  it("EMPTY_DRAFT 各字段默认值正确", () => {
    expect(EMPTY_DRAFT).toEqual({
      modelKey: "",
      aspectRatio: "1:1",
      count: 1,
      agentId: "",
      prompt: "",
      imageType: "none",
      referencePreview: [],
    })
  })
  it("NO_AGENT_VALUE 哨兵值存在", () => {
    expect(NO_AGENT_VALUE).toBe("__none__")
  })
})

describe("findModel", () => {
  const models: AiDesignModel[] = [
    {
      modelKey: "dall-e-3",
      displayName: "DALL-E 3",
      capabilities: ["IMAGE_GENERATE"],
      supportedAspectRatios: ["1:1", "16:9", "9:16"],
      maxOutputCount: 1,
      maxReferenceImages: 0,
    },
    {
      modelKey: "flux-pro",
      displayName: "Flux Pro",
      capabilities: ["IMAGE_GENERATE"],
      supportedAspectRatios: ["1:1", "3:4", "4:3", "16:9", "9:16"],
      maxOutputCount: 1,
      maxReferenceImages: 0,
    },
  ]

  it("命中 modelKey", () => {
    expect(findModel(models, "dall-e-3")?.displayName).toBe("DALL-E 3")
  })
  it("未命中返回 undefined", () => {
    expect(findModel(models, "unknown")).toBeUndefined()
  })
  it("空字符串返回 undefined", () => {
    expect(findModel(models, "")).toBeUndefined()
  })
})

describe("deriveLimits — 从模型能力派生 UI 约束", () => {
  it("未选模型 → 回退到默认上限（10 张 + 全比例）", () => {
    const l = deriveLimits(undefined)
    expect(l.maxCount).toBe(MAX_COUNT_PER_REQUEST)
    expect(l.supportedRatios).toBe(ASPECT_RATIOS)
    expect(l.maxRefImages).toBe(0)
  })

  it("DALL-E 3：maxCount=1，支持 3 种比例", () => {
    const m: AiDesignModel = {
      modelKey: "dall-e-3",
      displayName: "DALL-E 3",
      capabilities: ["IMAGE_GENERATE"],
      supportedAspectRatios: ["1:1", "16:9", "9:16"],
      maxOutputCount: 1,
      maxReferenceImages: 0,
    }
    const l = deriveLimits(m)
    expect(l.maxCount).toBe(1)
    expect(l.supportedRatios).toEqual(["1:1", "16:9", "9:16"])
  })

  it("模型 maxOutputCount 超过 MAX_COUNT_PER_REQUEST 时被钳到 10", () => {
    const m: AiDesignModel = {
      modelKey: "custom",
      displayName: "Custom",
      capabilities: ["IMAGE_GENERATE"],
      supportedAspectRatios: ["1:1"],
      maxOutputCount: 50,
      maxReferenceImages: 0,
    }
    expect(deriveLimits(m).maxCount).toBe(MAX_COUNT_PER_REQUEST)
  })

  it("空 supportedAspectRatios → 回退到全比例", () => {
    const m: AiDesignModel = {
      modelKey: "x",
      displayName: "X",
      capabilities: ["IMAGE_GENERATE"],
      supportedAspectRatios: [],
      maxOutputCount: 1,
      maxReferenceImages: 0,
    }
    expect(deriveLimits(m).supportedRatios).toBe(ASPECT_RATIOS)
  })

  it("maxRefImages 从模型读取", () => {
    const m: AiDesignModel = {
      modelKey: "custom",
      displayName: "Custom",
      capabilities: ["IMAGE_GENERATE"],
      supportedAspectRatios: ["1:1"],
      maxOutputCount: 1,
      maxReferenceImages: 3,
    }
    expect(deriveLimits(m).maxRefImages).toBe(3)
  })
})

describe("clampCount", () => {
  it("正常值原样返回", () => {
    expect(clampCount(3, 10)).toBe(3)
  })
  it("0 或负数回退到 1", () => {
    expect(clampCount(0, 10)).toBe(1)
    expect(clampCount(-5, 10)).toBe(1)
  })
  it("超过上限钳到上限", () => {
    expect(clampCount(999, 10)).toBe(10)
  })
  it("NaN 回退到 1", () => {
    expect(clampCount(Number.NaN, 10)).toBe(1)
  })
  it("小数向下取整", () => {
    expect(clampCount(3.7, 10)).toBe(3)
  })
})

describe("normalizeAspectRatio", () => {
  it("当前值在支持列表内 → 原样", () => {
    expect(normalizeAspectRatio("1:1", ["1:1", "16:9"])).toBe("1:1")
  })
  it("当前值不在支持列表 → 回退到第一个", () => {
    expect(normalizeAspectRatio("3:4", ["1:1", "16:9"])).toBe("1:1")
  })
  it("空支持列表 → 原样返回", () => {
    expect(normalizeAspectRatio("1:1", [])).toBe("1:1")
  })
})

describe("estimatePoints", () => {
  it("count=1 → 1.5 积分", () => {
    expect(estimatePoints(1)).toBe(1.5)
  })
  it("count=3 → 4.5 积分", () => {
    expect(estimatePoints(3)).toBe(4.5)
  })
  it("count 超过上限 → 按上限计", () => {
    expect(estimatePoints(999)).toBe(15) // 10 × 1.5
  })
  it("支持自定义单价", () => {
    expect(estimatePoints(2, 2)).toBe(4)
  })
})

describe("validateDraft — 生成请求前置校验", () => {
  const model: AiDesignModel = {
    modelKey: "dall-e-3",
    displayName: "DALL-E 3",
    capabilities: ["IMAGE_GENERATE"],
    supportedAspectRatios: ["1:1", "16:9", "9:16"],
    maxOutputCount: 1,
    maxReferenceImages: 0,
  }

  it("空模型 → 报错", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, prompt: "hi" }, model)).toMatch(/模型/)
  })
  it("空 prompt → 报错", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, modelKey: "dall-e-3" }, model)).toMatch(/prompt/)
  })
  it("prompt 只有空白 → 报错", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "   " }, model)).toMatch(/prompt/)
  })
  it("aspectRatio 不在模型支持 → 报错", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "hi", aspectRatio: "3:4" }, model)).toMatch(/宽高比/)
  })
  it("count 超过 MAX_COUNT_PER_REQUEST → 报错", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "hi", count: 999 }, model)).toMatch(/张数/)
  })
  it("count 超过模型 maxOutputCount → 报错", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "hi", count: 3 }, model)).toMatch(/最多一次/)
  })
  it("合法 draft → 通过", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "hi", count: 1 }, model)).toBeNull()
  })
  it("未选模型也通过 validateDraft（不传 model 参数时不校验模型约束）", () => {
    expect(validateDraft({ ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "hi" }, undefined)).toBeNull()
  })
})

describe("buildGeneratePayload — 请求体结构", () => {
  it("最小合法请求体：model_key / prompt / reference_images 三字段", () => {
    const draft: ImageStudioDraft = { ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "a red apple" }
    const payload = buildGeneratePayload(draft)
    expect(payload).toEqual({
      model_key: "dall-e-3",
      prompt: "a red apple",
      reference_images: [],
      aspect_ratio: "1:1",
      count: 1,
    })
  })

  it("带 agent_id 时透传", () => {
    const payload = buildGeneratePayload({
      ...EMPTY_DRAFT,
      modelKey: "dall-e-3",
      prompt: "hi",
      agentId: "agent_abc",
    })
    expect(payload.agent_id).toBe("agent_abc")
  })

  it("agent_id 为空时不携带该字段", () => {
    const payload = buildGeneratePayload({
      ...EMPTY_DRAFT,
      modelKey: "dall-e-3",
      prompt: "hi",
      agentId: "",
    })
    expect(payload.agent_id).toBeUndefined()
  })

  it("带 idempotencyKey → 写入 idempotency_key 字段", () => {
    const payload = buildGeneratePayload(
      { ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "hi" },
      { idempotencyKey: "gen_123_abc" },
    )
    expect(payload.idempotency_key).toBe("gen_123_abc")
  })

  it("空 idempotencyKey → 不携带", () => {
    const payload = buildGeneratePayload(
      { ...EMPTY_DRAFT, modelKey: "dall-e-3", prompt: "hi" },
      { idempotencyKey: "" },
    )
    expect(payload.idempotency_key).toBeUndefined()
  })

  it("reference_images 始终为空数组（M1 provider 全部 maxReferenceImages=0）", () => {
    const draft: ImageStudioDraft = {
      ...EMPTY_DRAFT,
      modelKey: "dall-e-3",
      prompt: "hi",
      referencePreview: [
        { id: "1", fileName: "a.png", dataUrl: "data:image/png;base64,xx", size: 100 },
      ],
    }
    const payload = buildGeneratePayload(draft)
    expect(payload.reference_images).toEqual([])
  })
})

describe("makeIdempotencyKey", () => {
  it("格式为 gen_<ts>_<random>", () => {
    const k = makeIdempotencyKey(1234)
    expect(k.startsWith("gen_1234_")).toBe(true)
    expect(k.length).toBeGreaterThan("gen_1234_".length)
  })
  it("两次调用返回不同 key", () => {
    expect(makeIdempotencyKey()).not.toBe(makeIdempotencyKey())
  })
})

describe("isAcceptedImage / filterAcceptedFiles", () => {
  it("接受 image/jpeg/png/webp", () => {
    expect(isAcceptedImage({ type: "image/jpeg" })).toBe(true)
    expect(isAcceptedImage({ type: "image/png" })).toBe(true)
    expect(isAcceptedImage({ type: "image/webp" })).toBe(true)
  })
  it("拒绝 gif/svg/pdf", () => {
    expect(isAcceptedImage({ type: "image/gif" })).toBe(false)
    expect(isAcceptedImage({ type: "image/svg+xml" })).toBe(false)
    expect(isAcceptedImage({ type: "application/pdf" })).toBe(false)
  })
  it("无 MIME 时用扩展名兜底", () => {
    expect(isAcceptedImage({ name: "a.png" })).toBe(true)
    expect(isAcceptedImage({ name: "a.JPEG" })).toBe(true)
    expect(isAcceptedImage({ name: "a.webp" })).toBe(true)
    expect(isAcceptedImage({ name: "a.gif" })).toBe(false)
  })
  it("filterAcceptedFiles 过滤非法文件", () => {
    const files = [
      new File(["x"], "a.png", { type: "image/png" }),
      new File(["x"], "b.gif", { type: "image/gif" }),
      new File(["x"], "c.webp", { type: "image/webp" }),
    ]
    const ok = filterAcceptedFiles(files)
    expect(ok).toHaveLength(2)
    expect(ok.map((f) => f.name)).toEqual(["a.png", "c.webp"])
  })
})

describe("imageTypeHint", () => {
  it("'none' 返回空字符串", () => {
    expect(imageTypeHint("none")).toBe("")
  })
  it("cover 返回封面图提示", () => {
    expect(imageTypeHint("cover")).toMatch(/封面/)
  })
  it("illustration 返回配图提示", () => {
    expect(imageTypeHint("illustration")).toMatch(/配图/)
  })
  it("poster 返回海报提示", () => {
    expect(imageTypeHint("poster")).toMatch(/海报/)
  })
  it("white-bg 返回白底图提示", () => {
    expect(imageTypeHint("white-bg")).toMatch(/白底/)
  })
})

describe("normalizeRecord — 后端记录规范化", () => {
  it("数字 created_at 直接透传", () => {
    const r = normalizeRecord({
      id: 1,
      model_key: "dall-e-3",
      prompt: "hi",
      images: ["https://x/1.png"],
      created_at: 1700000000,
      count: 1,
      aspect_ratio: "1:1",
    })
    expect(r.id).toBe("1")
    expect(r.createdAt).toBe(1700000000)
    expect(r.modelKey).toBe("dall-e-3")
    expect(r.images).toEqual(["https://x/1.png"])
  })

  it("字符串 created_at → Date.parse", () => {
    const r = normalizeRecord({
      task_id: "gen_abc",
      model_key: "flux-pro",
      prompt: "hi",
      images: [],
      created_at: "2026-10-18T00:00:00Z",
    })
    expect(r.id).toBe("gen_abc")
    expect(r.createdAt).toBe(Date.parse("2026-10-18T00:00:00Z"))
  })

  it("字段缺失时使用默认值", () => {
    const r = normalizeRecord({ model_key: "x", prompt: "p", images: [] })
    expect(r.id).toBe("")
    expect(r.aspectRatio).toBe("1:1")
    expect(r.count).toBe(0)
    expect(r.createdAt).toBe(0)
    expect(r.pointsTotal).toBe(0)
  })

  it("非数组 images → 空数组", () => {
    const r = normalizeRecord({ model_key: "x", prompt: "p", images: "bad" as unknown as string[] })
    expect(r.images).toEqual([])
  })

  it("points.total 被读取到 pointsTotal", () => {
    const r = normalizeRecord({
      model_key: "x",
      prompt: "p",
      images: [],
      points: { unit: 1.5, total: 4.5, status: "consumed" },
    })
    expect(r.pointsTotal).toBe(4.5)
  })
})

describe("buildEditorUrl — M5 跳转", () => {
  it("把图片 URL 编码进 query", () => {
    expect(buildEditorUrl("https://x.com/1.png")).toBe("/tools/image-editor?url=https%3A%2F%2Fx.com%2F1.png")
  })
  it("带查询参数的 URL 被正确编码", () => {
    const url = "https://x.com/1.png?token=a%20b"
    const out = buildEditorUrl(url)
    expect(out.startsWith("/tools/image-editor?url=")).toBe(true)
    expect(decodeURIComponent(out.split("?url=")[1])).toBe(url)
  })
  it("data URL 也能构造", () => {
    const data = "data:image/png;base64,AAA"
    expect(decodeURIComponent(buildEditorUrl(data).split("?url=")[1])).toBe(data)
  })
})
