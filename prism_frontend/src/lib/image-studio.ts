/**
 * M1 前端 · AI 生图工作台（/fusion/image-studio）纯逻辑层。
 *
 * 参考澜途 AI 图片设计（PRD §5），按自媒体场景裁剪：
 *   - 素材图上传（UI 骨架，本地预览，不真的上传到后端）
 *   - 模型选择（/api/v1/ai-design/capabilities）
 *   - 宽高比 + 生成张数 + 智能体 + prompt
 *   - 图片类型（先做封面/配图/海报/白底 4 种常用）
 *   - 积分估算 + 生成（/api/v1/ai-design/generate）
 *   - 生成记录（/api/v1/ai-design/records）
 *
 * 本文件只做纯函数与常量，UI 在 `prism_frontend/src/app/fusion/image-studio/page.tsx` 消费。
 * 抽离原则与 M2 (`agent-studio.ts`) / M4 (`wizard-core.ts`) 一致：便于脱离 React 单测。
 */

// ──────────────────────────────────────────────────────────────
// 后端接口契约（对齐 M1 · prism_backend/fusion_ai/ai_design.py）
// ──────────────────────────────────────────────────────────────

export interface AiDesignModel {
  modelKey: string
  displayName: string
  version?: number
  capabilities: string[]
  supportedAspectRatios: string[]
  maxOutputCount: number
  maxReferenceImages: number
  supportedInputMediaTypes?: string[]
}

export interface AiDesignCapabilities {
  models: AiDesignModel[]
}

export interface AiDesignGenerateRequest {
  model_key: string
  prompt: string
  reference_images: string[]
  aspect_ratio?: string
  count?: number
  agent_id?: string
  idempotency_key?: string
}

export interface AiDesignPoints {
  unit: number
  total: number
  freeze_tx_id?: number
  status: string
}

export interface AiDesignGenerateResponse {
  task_id: string
  model_key: string
  aspect_ratio?: string
  count?: number
  images: string[]
  agent_id?: string
  points?: AiDesignPoints
  record_id?: string
}

export interface AiDesignRecord {
  id?: string | number
  task_id?: string
  model_key: string
  prompt: string
  aspect_ratio?: string
  count?: number
  images: string[]
  agent_id?: string
  created_at?: number | string
  points?: AiDesignPoints
  [k: string]: unknown
}

export interface AiDesignRecordsPage {
  total: number
  current: number
  size: number
  records: AiDesignRecord[]
}

// ──────────────────────────────────────────────────────────────
// 常量（与后端 _MAX_COUNT_PER_REQUEST + 澜途 PRD 对齐）
// ──────────────────────────────────────────────────────────────

/** 后端硬上限（prism_backend/fusion_ai/ai_design.py::_MAX_COUNT_PER_REQUEST） */
export const MAX_COUNT_PER_REQUEST = 10

/** M1 积分单价：每张图片（澜途 §5 · AI设计中心 1.5 积分/张；与云端 pricing 一致） */
export const AI_IMAGE_UNIT_POINTS = 1.5

/** 素材上传：最大张数（澜途 PRD 允许最多 7 张参考图；自媒体素材场景同样保留 7） */
export const MAX_REFERENCE_IMAGES = 7

/** 素材上传：接受的文件类型（JPG / PNG / WebP） */
export const ACCEPTED_IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"] as const
export type AcceptedImageType = (typeof ACCEPTED_IMAGE_TYPES)[number]

/** 常见宽高比选项（澜途 AI 图片设计 §3.1） */
export const ASPECT_RATIOS = [
  "1:1",
  "3:4",
  "4:3",
  "16:9",
  "9:16",
] as const
export type AspectRatio = (typeof ASPECT_RATIOS)[number]

/** 图片类型（澜途 21 种的自媒体裁剪子集；后续可扩） */
export const IMAGE_TYPES = [
  { id: "cover", label: "封面图", description: "标题字号大、留白多的首屏视觉" },
  { id: "illustration", label: "配图", description: "正文插图，与文字风格统一" },
  { id: "poster", label: "海报", description: "信息层级完整的宣传素材" },
  { id: "white-bg", label: "白底图", description: "干净底色的商品 / 头像素材" },
] as const
export type ImageTypeId = (typeof IMAGE_TYPES)[number]["id"]

/** 智能体下拉的哨兵值（与 M4 `AgentPickerStep` 保持一致） */
export const NO_AGENT_VALUE = "__none__"

// ──────────────────────────────────────────────────────────────
// 前端表单状态（页面持有；纯逻辑层不依赖 React）
// ──────────────────────────────────────────────────────────────

export interface ImageStudioDraft {
  /** 模型选择（空字符串表示未选择） */
  modelKey: string
  /** 宽高比（默认 1:1） */
  aspectRatio: string
  /** 生成张数（1..maxCount） */
  count: number
  /** 智能体 id（空字符串表示不使用） */
  agentId: string
  /** prompt 文本 */
  prompt: string
  /** 图片类型（"none" 表示未选择，仅作为提示注入 prompt） */
  imageType: ImageTypeId | "none"
  /** 素材图本地预览（dataURL，不真的上传） */
  referencePreview: ReferencePreview[]
}

export interface ReferencePreview {
  id: string
  fileName: string
  dataUrl: string
  size: number
}

export const EMPTY_DRAFT: ImageStudioDraft = {
  modelKey: "",
  aspectRatio: "1:1",
  count: 1,
  agentId: "",
  prompt: "",
  imageType: "none",
  referencePreview: [],
}

// ──────────────────────────────────────────────────────────────
// 纯函数：能力 / 约束 / 派生
// ──────────────────────────────────────────────────────────────

/** 从 capabilities 列表找出模型；未命中返回 undefined */
export function findModel(
  models: AiDesignModel[],
  modelKey: string,
): AiDesignModel | undefined {
  if (!modelKey) return undefined
  return models.find((m) => m.modelKey === modelKey)
}

/**
 * 根据当前模型能力决定 UI 可选项：
 *   - supportedRatios：模型支持的宽高比（若无选择，回退到 ASPECT_RATIOS 全集）
 *   - maxCount：`min(模型 maxOutputCount, MAX_COUNT_PER_REQUEST)`；未选模型时默认为 MAX_COUNT_PER_REQUEST
 *   - maxRefImages：模型允许参考图数量（当前 M1 全部 provider 都是 0）
 */
export function deriveLimits(model: AiDesignModel | undefined): {
  supportedRatios: readonly string[]
  maxCount: number
  maxRefImages: number
} {
  if (!model) {
    return {
      supportedRatios: ASPECT_RATIOS,
      maxCount: MAX_COUNT_PER_REQUEST,
      maxRefImages: 0,
    }
  }
  const supportedRatios =
    Array.isArray(model.supportedAspectRatios) && model.supportedAspectRatios.length > 0
      ? model.supportedAspectRatios
      : ASPECT_RATIOS
  const maxCount = Math.max(
    1,
    Math.min(model.maxOutputCount || 1, MAX_COUNT_PER_REQUEST),
  )
  return {
    supportedRatios,
    maxCount,
    maxRefImages: model.maxReferenceImages || 0,
  }
}

/** 把 count 钳到 [1, maxCount]；无效值回退到 1 */
export function clampCount(raw: number, maxCount: number): number {
  if (!Number.isFinite(raw) || raw < 1) return 1
  const n = Math.floor(raw)
  return n > maxCount ? maxCount : n
}

/** 若当前 aspectRatio 不在 supported 中，返回 fallback（第一个支持的比例） */
export function normalizeAspectRatio(
  current: string,
  supported: readonly string[],
): string {
  if (!Array.isArray(supported) || supported.length === 0) return current
  return supported.includes(current) ? current : supported[0]
}

/** 计算预计消耗积分：count × 单价 */
export function estimatePoints(count: number, unit = AI_IMAGE_UNIT_POINTS): number {
  const safe = clampCount(count, MAX_COUNT_PER_REQUEST)
  return Number((safe * unit).toFixed(2))
}

// ──────────────────────────────────────────────────────────────
// 图片类型 → prompt 前缀（辅助用户，可选注入）
// ──────────────────────────────────────────────────────────────

/** 每种图片类型给出的 prompt 提示词片段（不改动用户原始输入） */
const IMAGE_TYPE_HINTS: Record<ImageTypeId, string> = {
  cover: "封面图：标题字号大、留白多、首屏视觉冲击",
  illustration: "配图：与文字风格统一的正文插图",
  poster: "海报：信息层级完整、可加文字排版",
  "white-bg": "白底图：干净白色背景、居中主体",
}

export function imageTypeHint(id: ImageTypeId | "none"): string {
  if (id === "none") return ""
  return IMAGE_TYPE_HINTS[id] ?? ""
}

// ──────────────────────────────────────────────────────────────
// 生成请求体构造（对齐 M1 · POST /api/v1/ai-design/generate）
// ──────────────────────────────────────────────────────────────

/**
 * 构造生成请求体：
 *   - `model_key` / `prompt` 必填（调用方已校验）
 *   - `reference_images` 传空数组（M1 当前 provider 全部 maxReferenceImages=0；有图则会被后端 400）
 *   - `agent_id` 只有选了智能体时才带上；空串省略
 *   - `idempotency_key` 若传入则带上，用于防重
 *   - `aspect_ratio` / `count` 只在值有效时带上，让后端使用默认
 */
export function buildGeneratePayload(
  draft: ImageStudioDraft,
  opts: { idempotencyKey?: string } = {},
): AiDesignGenerateRequest {
  const body: AiDesignGenerateRequest = {
    model_key: draft.modelKey,
    prompt: draft.prompt,
    reference_images: [],
  }
  if (draft.aspectRatio) body.aspect_ratio = draft.aspectRatio
  if (draft.count > 0) body.count = draft.count
  if (draft.agentId) body.agent_id = draft.agentId
  if (opts.idempotencyKey) body.idempotency_key = opts.idempotencyKey
  return body
}

/** 校验生成请求是否合法；返回首个错误消息，通过返回 null */
export function validateDraft(
  draft: ImageStudioDraft,
  model: AiDesignModel | undefined,
): string | null {
  if (!draft.modelKey) return "请选择模型"
  if (!draft.prompt || !draft.prompt.trim()) return "请填写 prompt"
  if (model && draft.aspectRatio && !model.supportedAspectRatios.includes(draft.aspectRatio)) {
    return `当前模型不支持 ${draft.aspectRatio} 宽高比`
  }
  if (draft.count < 1) return "生成张数至少为 1"
  if (draft.count > MAX_COUNT_PER_REQUEST) {
    return `生成张数不能超过 ${MAX_COUNT_PER_REQUEST}`
  }
  if (model && draft.count > model.maxOutputCount) {
    return `模型 ${model.displayName} 最多一次生成 ${model.maxOutputCount} 张`
  }
  return null
}

/** 生成幂等 key（同页多次点击可生成不同 key；测试时可传固定前缀方便断言） */
export function makeIdempotencyKey(nowMs = Date.now()): string {
  return `gen_${nowMs}_${Math.random().toString(36).slice(2, 10)}`
}

// ──────────────────────────────────────────────────────────────
// 素材上传本地预览（不真的上传后端；UI 骨架）
// ──────────────────────────────────────────────────────────────

/** 客户端 MIME 校验：接受 image/jpeg/png/webp */
export function isAcceptedImage(file: { type?: string; name?: string }): boolean {
  const t = (file.type || "").toLowerCase()
  if (ACCEPTED_IMAGE_TYPES.includes(t as AcceptedImageType)) return true
  // 无 MIME 时看扩展名兜底
  const n = (file.name || "").toLowerCase()
  return n.endsWith(".jpg") || n.endsWith(".jpeg") || n.endsWith(".png") || n.endsWith(".webp")
}

export function filterAcceptedFiles(files: File[]): File[] {
  return files.filter(isAcceptedImage)
}

// ──────────────────────────────────────────────────────────────
// 记录列表：把后端 records 转成前端展示态
// ──────────────────────────────────────────────────────────────

export interface NormalizedRecord {
  id: string
  taskId: string
  modelKey: string
  prompt: string
  aspectRatio: string
  count: number
  images: string[]
  agentId: string
  createdAt: number
  pointsTotal: number
}

export function normalizeRecord(r: AiDesignRecord): NormalizedRecord {
  const createdAt = typeof r.created_at === "number"
    ? r.created_at
    : typeof r.created_at === "string"
      ? Date.parse(r.created_at) || 0
      : 0
  return {
    id: String(r.id ?? r.task_id ?? ""),
    taskId: String(r.task_id ?? r.id ?? ""),
    modelKey: r.model_key,
    prompt: r.prompt,
    aspectRatio: r.aspect_ratio ?? "1:1",
    count: r.count ?? 0,
    images: Array.isArray(r.images) ? r.images : [],
    agentId: r.agent_id ?? "",
    createdAt,
    pointsTotal: r.points?.total ?? 0,
  }
}

// ──────────────────────────────────────────────────────────────
// M5 编辑器跳转：URL 拼接
// ──────────────────────────────────────────────────────────────

/**
 * 拼 /tools/image-editor 跳转链接；带 url 参数。
 * M5 侧通过 ?url= 参数自动加载，见 `prism_frontend/src/app/tools/image-editor/page.tsx`。
 */
export function buildEditorUrl(imageUrl: string): string {
  return `/tools/image-editor?url=${encodeURIComponent(imageUrl)}`
}
