/**
 * M2 · AI Agent Studio 前端逻辑（从 UI 拆出，便于测试）。
 *
 * 参考澜途 "AI AGENT STUDIO"（/system/ai-agents）：
 *   - 用户提交训练素材（名称 + 样例内容 + 设计原则）
 *   - 后端调 LLM 分析并生成 style_prompt，存为智能体
 *   - 配额默认 2，付费墙
 *
 * 本文件只做纯逻辑，UI 在 page.tsx 里消费。
 */

export interface AgentPublic {
  id: string
  name: string
  description: string
  style_prompt: string
  sample_contents: string[]
  design_principles: string
  style_tokens: number
  created_at: number
  updated_at: number
}

export interface AgentQuota {
  limit: number
  used: number
  canCreate: boolean
  upgrade_url: string
}

export interface CreateAgentPayload {
  name: string
  description?: string
  sample_contents: string[] | string
  design_principles?: string
}

export interface CreateAgentFormState {
  name: string
  description: string
  sample_contents: string
  design_principles: string
}

export interface ValidationResult {
  ok: boolean
  errors: Partial<Record<keyof CreateAgentFormState, string>>
}

/**
 * 澜途对齐的字段限制：
 *   - 名称 ≤ 80 字符（后端一致）
 *   - 描述 ≤ 500 字符
 *   - 设计原则 ≤ 12000 字符（澜途硬上限）
 *   - 样例内容至少一条非空
 */
export const AGENT_LIMITS = {
  nameMax: 80,
  descriptionMax: 500,
  designPrinciplesMax: 12000,
} as const

/**
 * 从多行文本（每行一条样例）构造 API 请求体。
 *
 * - 空行会被自动过滤
 * - 若整段全空 → 返回 null，UI 应禁用提交按钮
 */
export function buildCreatePayload(
  state: CreateAgentFormState,
): CreateAgentPayload | null {
  const name = (state.name || "").trim()
  if (!name) return null
  const samples = (state.sample_contents || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)
  if (samples.length === 0) return null
  return {
    name,
    description: (state.description || "").trim(),
    sample_contents: samples,
    design_principles: (state.design_principles || "").trim(),
  }
}

/**
 * 表单校验（前端预检，非权威；后端仍会校验）。
 *
 * 返回 errors 字典，key = 字段名，value = 简短错误消息。
 */
export function validateAgentForm(
  state: CreateAgentFormState,
): ValidationResult {
  const errors: Partial<Record<keyof CreateAgentFormState, string>> = {}
  const name = (state.name || "").trim()
  if (!name) {
    errors.name = "请输入智能体名称"
  } else if (name.length > AGENT_LIMITS.nameMax) {
    errors.name = `名称不能超过 ${AGENT_LIMITS.nameMax} 字`
  }

  const samples = (state.sample_contents || "")
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean)
  if (samples.length === 0) {
    errors.sample_contents = "请至少填写一条样例内容（可分多行）"
  }

  const desc = (state.description || "").trim()
  if (desc.length > AGENT_LIMITS.descriptionMax) {
    errors.description = `描述不能超过 ${AGENT_LIMITS.descriptionMax} 字`
  }

  const principles = state.design_principles || ""
  if (principles.length > AGENT_LIMITS.designPrinciplesMax) {
    errors.design_principles = `设计原则不能超过 ${AGENT_LIMITS.designPrinciplesMax} 字`
  }

  return {
    ok: Object.keys(errors).length === 0,
    errors,
  }
}

/**
 * 配额 UI 派生：
 *   - 创建按钮是否禁用
 *   - 显示文本 "used/limit"
 *   - 是否显示"升级套餐"提示
 */
export function quotaUI(quota: AgentQuota | null) {
  if (!quota) return { disabled: true, label: "…", showUpgrade: false }
  const disabled = !quota.canCreate
  const label = `${quota.used}/${quota.limit}`
  return {
    disabled,
    label,
    showUpgrade: disabled && !!quota.upgrade_url,
  }
}

/**
 * 把 style_prompt 截断成卡片上显示的摘要。
 */
export function summarizeStylePrompt(prompt: string, maxLen = 80): string {
  const s = (prompt || "").trim()
  if (!s) return "（无 style_prompt）"
  return s.length > maxLen ? s.slice(0, maxLen) + "…" : s
}

/**
 * 空表单初始状态。
 */
export const EMPTY_FORM: CreateAgentFormState = {
  name: "",
  description: "",
  sample_contents: "",
  design_principles: "",
}
