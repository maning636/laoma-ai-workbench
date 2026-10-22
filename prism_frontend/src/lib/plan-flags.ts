/**
 * Open Core · Plan Flags 前端逻辑（从 UI 拆出，便于测试）。
 *
 * 与 `cloud_service/billing/feature_gate.py` 对齐的浏览器侧镜像：
 *   - `GET /cloud/feature-flags` 返回 `{plan, flags}`；
 *   - 云端不可达 / 未登录 / 401 → 前端一律回落 Community（不阻断 UI）。
 *
 * 本文件只做纯逻辑：
 *   1. 类型定义与 flag 常量（`FEATURE_NAMES`）
 *   2. 默认 Community flags 快照（云端不可达时使用）
 *   3. `normalizeFlags` / `buildPlanBadgeView` / `formatLimit` 派生函数
 *
 * UI 层（`plan-badge.tsx`）与云端 API 调用逻辑都基于本文件。
 */

export type PlanName = "community" | "pro"

/** Open Core 全量 feature 名（与 feature_gate.FEATURE_NAMES 保持一致） */
export const FEATURE_NAMES = [
  "max_accounts",
  "max_platforms",
  "ai_mode",
  "image_gen",
  "agent_quota",
  "data_recovery",
  "persona",
  "proxy_management",
  "stream_chat",
  "team_members",
] as const

export type FeatureName = (typeof FEATURE_NAMES)[number]

/** 允许 `Any` 值：数值/布尔/字符串（"cloud" | "local_key"）共存。 */
export type FeatureFlags = Partial<Record<FeatureName, number | boolean | string>>

/** `GET /cloud/feature-flags` 响应。 */
export interface FeatureFlagsResponse {
  plan: PlanName
  flags: FeatureFlags
  upgrade_url?: string | null
}

/** UI 派生视图：badge 组件消费。 */
export interface PlanBadgeView {
  plan: PlanName
  /** 是否 Pro */
  isPro: boolean
  /** 账号上限（-1 = 无限，0 = 明确禁止） */
  maxAccounts: number
  /** 平台上限 */
  maxPlatforms: number
  /** 智能体配额 */
  agentQuota: number
  /** 账号配额文案（"3" / "无限" / "0"） */
  accountsLabel: string
  /** 平台配额文案 */
  platformsLabel: string
  /** 智能体配额文案（"0" / "2" / "无限"） */
  agentLabel: string
  /** 升级入口 URL（"加微信开通" / "续费联系"） */
  upgradeUrl: string
  /** Pro 用户看到的动作按钮文案 */
  actionLabel: string
}

/** 云端不可达时的默认 Community flags。 */
export const DEFAULT_COMMUNITY_FLAGS: FeatureFlags = {
  max_accounts: 3,
  max_platforms: 3,
  ai_mode: "local_key",
  image_gen: "local_key",
  agent_quota: 0,
  data_recovery: true,
  persona: false,
  proxy_management: false,
  stream_chat: false,
  team_members: 1,
}

/**
 * 默认升级 URL。
 *
 * 线上支付已下线(2026-10-22),没有「在线下单」页面可跳 —— 统一指向
 * 设置页的「联系我们」区块(加微信人工办理 + 用户群)。
 */
export const DEFAULT_UPGRADE_URL = "/settings#contact"

/**
 * 把 flag 值格式化成人类可读文本：
 *   - -1 → "无限"
 *   - 其他数字 → 直接转字符串
 *   - 空/undefined → "—"
 */
export function formatLimit(value: number | string | boolean | null | undefined): string {
  if (value === -1) return "无限"
  if (typeof value === "number" && Number.isFinite(value)) return String(value)
  if (value === null || value === undefined || value === "") return "—"
  return String(value)
}

/**
 * 归一化云端 `GET /cloud/feature-flags` 响应。
 *
 * 行为：
 *   - 若 plan 非 "pro"，一律视为 "community"（未来扩展 team 等档位时前端保守处理）
 *   - flags 缺失项从默认 Community 补齐（Pro 时保留 Pro 语义：数值 -1 表无限）
 *   - 云端返回结构不完整（如 `{}`）时不抛错，UI 可正常渲染
 *   - 忽略未知 key（云端可能追加字段，例如未来扩展的 team_members 之外的档位）
 */
export function normalizeFlags(
  resp:
    | {
        plan?: string
        flags?: Record<string, unknown>
        upgrade_url?: string | null
      }
    | null
    | undefined,
): FeatureFlagsResponse {
  const rawPlan = (resp?.plan || "").toLowerCase()
  const plan: PlanName = rawPlan === "pro" ? "pro" : "community"

  const flags = (resp?.flags ?? {}) as Record<string, unknown>
  const merged: FeatureFlags = { ...DEFAULT_COMMUNITY_FLAGS }
  for (const key of FEATURE_NAMES) {
    const v = flags[key]
    if (v !== undefined && v !== null) {
      // 只接受 number/boolean/string；其他类型丢弃
      if (typeof v === "number" || typeof v === "boolean" || typeof v === "string") {
        merged[key] = v
      }
    }
  }

  return {
    plan,
    flags: merged,
    upgrade_url: resp?.upgrade_url ?? null,
  }
}

/**
 * 从 FeatureFlags 派生 UI 视图。
 *
 * 设计说明：
 *   - Community 用户 `max_accounts=3, max_platforms=3` → 显示 "3" / "3"
 *   - Pro 用户 `max_accounts=-1` → 账号显示 "无限"；平台**不承诺具体数量**（D5），显示 "多"
 *   - `agent_quota=0`（Community） → 显示 "0"，同时 badge 展示 "升级解锁智能体"
 *   - `upgrade_url` 缺失时回落到 `DEFAULT_UPGRADE_URL`
 */
export function buildPlanBadgeView(
  flags: FeatureFlagsResponse,
  opts: { upgradeUrl?: string } = {},
): PlanBadgeView {
  const f = flags.flags
  const maxAccounts = Number(f.max_accounts ?? DEFAULT_COMMUNITY_FLAGS.max_accounts)
  const maxPlatforms = Number(f.max_platforms ?? DEFAULT_COMMUNITY_FLAGS.max_platforms)
  const agentQuota = Number(f.agent_quota ?? DEFAULT_COMMUNITY_FLAGS.agent_quota)

  const upgradeUrl = opts.upgradeUrl || flags.upgrade_url || DEFAULT_UPGRADE_URL

  return {
    plan: flags.plan,
    isPro: flags.plan === "pro",
    maxAccounts,
    maxPlatforms,
    agentQuota,
    accountsLabel: formatLimit(maxAccounts),
    platformsLabel: maxPlatforms === -1 ? "无限" : flags.plan === "pro" ? "多" : formatLimit(maxPlatforms), // D5：Pro 不承诺具体平台数量，不写死数字
    agentLabel: formatLimit(agentQuota),
    upgradeUrl,
    // 线上支付下线：Pro 用户看到"续费联系"，Community 看到"加微信开通"
    // （都指向设置页的「联系我们」区块，走人工充值拿注册码的路径）
    actionLabel: flags.plan === "pro" ? "续费联系" : "加微信开通",
  }
}

/**
 * 从 flags 里查询单个 feature 的"是否允许"，用于 UI 侧硬限。
 *
 * 规则：
 *   - 数值型（max_accounts / max_platforms / agent_quota / team_members）
 *     0 表示明确禁止（return false）；-1 或 >0 视为允许
 *   - 布尔型（data_recovery / persona / …）→ 直接返回布尔值
 *   - 字符串型（ai_mode / image_gen）→ 只要不为空视为允许
 */
export function isFeatureAllowed(
  flags: FeatureFlagsResponse,
  name: FeatureName,
): boolean {
  const value = flags.flags[name]
  if (value === undefined || value === null) return false
  if (typeof value === "boolean") return value
  if (typeof value === "number") return value !== 0
  if (typeof value === "string") return value.length > 0
  return false
}
