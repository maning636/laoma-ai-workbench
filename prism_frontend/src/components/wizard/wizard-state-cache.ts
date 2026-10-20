/**
 * M4 · 场景引导 Wizard 跨步骤状态缓存。
 *
 * 设计：
 *   - Wizard 组件的 `step.render(ctx)` 会在切换步骤时被 Suspense fallback 卸载
 *     再重挂载（同 M2 中 `AgentPickerStep` 的 `_agentIdCache` 模式）。
 *   - 每个场景的步骤内容需要共享用户的选择（选中的平台、输入的话题、生成的标题
 *     等），如果仅用局部 state，切步后会被清空。
 *   - 用模块级 `Map<sceneId, draft>` 存住"跨步 draft"；每个场景定义一个 Draft
 *     interface + 一个 key，避免不同场景的字段污染。
 *
 * 使用约定：
 *   - 每个步骤在渲染时用 `getSceneDraft<...>(KEY)` 恢复状态；
 *   - 用户输入变化时立即 `setSceneDraft(KEY, draft)` 持久化；
 *   - Wizard RESET（回到场景列表）时调用 `clearSceneDraft(KEY)` 清理，避免
 *     下次进入场景仍显示上次数据。
 *
 * 与 `_agentIdCache` 的关系：AgentPickerStep 已经用 module-level cache 存了
 *   智能体选择，并派发 `prism-wizard:agent-selected` CustomEvent。这里通过
 *   `subscribeAgentChange` 监听该事件，把 agent_id 写入 AI_IMAGE Draft，供
 *   后续步骤（生成 / 结果）读取。
 */

export interface AiWritingDraft {
  /** 步骤1：选中的平台 id 列表（如 ["douyin", "xhs"]） */
  platformIds: string[]
  /** 步骤2：用户输入的选题（可能由"AI 生成选题" mock 填充） */
  topic: string
  /** 步骤3：AI 生成的标题候选（3 条） */
  titleCandidates: string[]
  /** 步骤3：最终选中的标题 */
  title: string
  /** 步骤3：AI 生成的标签候选 */
  tags: string[]
  /** 步骤3：AI 生成的正文草稿 */
  body: string
  /** 步骤4：是否已 mock 发布 */
  published: boolean
  /** 步骤4：mock 发布完成时间（unix ms） */
  publishedAt: number
}

export interface AiImageDraft {
  /** 步骤1：本地预览的素材图（dataURL） */
  referencePreview: { fileName: string; dataUrl: string }[]
  /** 步骤2：AgentPickerStep 写入；"" 表示未选 */
  agentId: string
  /** 步骤3：选中的图片类型 id（image-studio.ts IMAGE_TYPES） */
  imageTypeId: string
  /** 步骤4：mock 生成的结果 URL 列表 */
  generatedUrls: string[]
  /** 步骤4：mock 任务 id（便于展示"生成中"过程） */
  generatedTaskId: string
}

export interface VideoPipelineDraft {
  /** 步骤1：选中的视频素材文件列表（仅存元信息，不存 blob） */
  materials: { fileName: string; size: number }[]
  /** 步骤2：Easel 流水线配置勾选 */
  config: {
    addSubtitle: boolean
    addCover: boolean
    addWatermark: boolean
    trimSilent: boolean
    autoBgm: boolean
  }
  /** 步骤3：mock 任务 id */
  taskId: string
}

const _sceneDrafts = new Map<string, unknown>()

export function getSceneDraft<D>(
  sceneId: string,
  initial: () => D,
): D {
  const cached = _sceneDrafts.get(sceneId)
  return cached ? (cached as D) : initial()
}

export function setSceneDraft<D>(sceneId: string, draft: D): void {
  _sceneDrafts.set(sceneId, draft)
}

export function clearSceneDraft(sceneId: string): void {
  _sceneDrafts.delete(sceneId)
}

export function clearAllSceneDrafts(): void {
  _sceneDrafts.clear()
}

/** 供测试用的只读快照（不拷贝） */
export function peekSceneDraft<D>(sceneId: string): D | undefined {
  return _sceneDrafts.get(sceneId) as D | undefined
}

// ──────────────────────────────────────────────────────────────
// AI_IMAGE 场景：监听 AgentPickerStep 的 CustomEvent，写入 Draft.agentId
// 该订阅幂等（多次调用不会重复绑定），由 AI_IMAGE 场景首次渲染步骤时触发。
// ──────────────────────────────────────────────────────────────

const AI_IMAGE_SCENE_ID = "ai-image"
const AGENT_CHANGE_EVENT = "prism-wizard:agent-selected"

let _agentSubscriberBound = false

/**
 * 监听 AgentPickerStep 派发的 agent 选择事件，同步到 AI_IMAGE Draft。
 * 幂等调用，可在步骤 4/5 组件挂载时安全重复调用。
 */
export function subscribeAgentChangeToDraft(): void {
  if (_agentSubscriberBound) return
  if (typeof window === "undefined") return
  window.addEventListener(AGENT_CHANGE_EVENT, ((e: Event) => {
    const detail = (e as CustomEvent).detail as
      | { agent_id?: string }
      | undefined
    const agentId = detail?.agent_id ?? ""
    const draft = getSceneDraft<AiImageDraft>(AI_IMAGE_SCENE_ID, () => ({
      referencePreview: [],
      agentId: "",
      imageTypeId: "",
      generatedUrls: [],
      generatedTaskId: "",
    }))
    draft.agentId = agentId
    setSceneDraft(AI_IMAGE_SCENE_ID, draft)
  }) as EventListener)
  _agentSubscriberBound = true
}

export function resetAgentSubscriberForTest(): void {
  _agentSubscriberBound = false
}
