/**
 * 注册码（license）前端类型与派生工具。
 *
 * 与后端 `prism_backend/fastapi_app/api/v1/license/router.py` 对齐：
 *   - GET    `/api/v1/license/status`          → LicenseStatusResponse
 *   - POST   `/api/v1/license/activate`        → LicenseStatusResponse + ok
 *   - DELETE `/api/v1/license/`                → LicenseStatusResponse + ok + cleared
 *   - GET    `/api/v1/license/effective-flags` → LicenseEffectiveFlagsResponse
 *                                             （2026-10-24 起响应形状与云端
 *                                               `/cloud/feature-flags` 对齐：
 *                                               `{plan, flags, upgrade_url, ...}`）
 *
 * 说明：
 *   - `license` 对象的字段是**snake_case / camelCase 混搭**
 *     （见 `fastapi_app/core/license.py::LicenseState.to_dict()`）；
 *   - 前端**不再**做「注册码 ∩ 云端」的二次交集运算 —— 后端
 *     `/effective-flags` 已经是最终交集结果；
 *   - 无有效注册码时前端保持云端原值（见 `mergeLicenseFlags`）。
 */

// ──────────────────────────────────────────────────────────────
// 类型
// ──────────────────────────────────────────────────────────────

/** 注册码状态（与 `license.py` 中的 `STATUS_*` 常量一一对应） */
export type LicenseStatus =
  | "missing" // 从未输入注册码
  | "active" // 有效期内
  | "grace" // 已到期，仍在宽限期内
  | "expired" // 已到期且宽限期满 → 只读
  | "invalid" // 格式错 / 签名不通过 / 条目非法
  | "not_yet_valid" // iat 在未来（时钟问题或伪造）

/** 6 个可组合的授权条目（与后端 `ENTITLEMENTS` 一致） */
export type LicenseEntitlement =
  | "core"
  | "ai_cloud"
  | "agent"
  | "persona"
  | "campaign"
  | "multi_platform"

/** 后端 `license` 对象的字段形状（**camelCase**：expiresAt / graceDays / licenseId / customer / hasToken） */
export interface LicenseState {
  status: LicenseStatus
  valid: boolean
  entitlements: string[]
  expiresAt: string | null
  graceDays: number
  readOnly: boolean
  licenseId: string | null
  customer: string | null
  message: string
  hasToken: boolean
  /**
   * 注册码携带的积分额度（2026-10-22 新增）。
   *
   * - 由签发端 `issue_license.py --credits N` 写入并随签名下发；
   * - 老版本注册码没有这个字段 → 后端按 0 返回；
   * - 云端在「注册码激活」时把这笔额度注入账户积分，
   *   之后管理员仍可随时增减（以云端余额为准）。
   */
  credits: number
}

/** flag 值可能是 number / boolean / string，与 `plan-flags.ts` 的 FeatureFlags 保持一致 */
export type LicenseFlagMap = Partial<Record<string, number | boolean | string>>

/** `GET /api/v1/license/status` 响应 */
export interface LicenseStatusResponse {
  license: LicenseState
  /** 注册码**本地维度**的 flag 档位（不掺云端） */
  licenseFlags: LicenseFlagMap
  /** 只读标记（D4：过期 + 宽限期满 → true） */
  readOnly: boolean
}

/** `GET /api/v1/license/effective-flags` 响应（**后端已完成交集运算**） */
export interface LicenseEffectiveFlagsResponse {
  /**
   * 档位（"community" | "pro"）—— 由后端从最终交集 flag 派生。
   * 与云端 `GET /cloud/feature-flags` 的 `plan` 同义。
   */
  plan: "community" | "pro"
  /** 双轨交集后的最终 flag */
  flags: LicenseFlagMap
  /** 当前注册码状态 */
  license: LicenseState
  /** 是否只读（同 status 响应） */
  readOnly: boolean
  /** 本次请求是否成功拉到云端 feature flags */
  cloudAvailable: boolean
  /** 升级入口（线上支付已下线 → 指向设置页「联系我们」） */
  upgrade_url?: string | null
}

/** 12 个 flag 名（与后端 `FLAG_CAPACITY` 完全一致） */
export const LICENSE_FLAG_NAMES = [
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
  "cloud_prompt",
  "campaign_orchestration",
] as const

export type LicenseFlagName = (typeof LICENSE_FLAG_NAMES)[number]

// ──────────────────────────────────────────────────────────────
// 授权条目中文名映射
// ──────────────────────────────────────────────────────────────

/** 6 个授权条目的中文显示名（UI 徽标直接使用） */
export const ENTITLEMENT_LABELS: Record<LicenseEntitlement, string> = {
  core: "基础包",
  ai_cloud: "云端 AI",
  agent: "Agent 配额",
  persona: "Persona 与代理",
  campaign: "营销活动编排",
  multi_platform: "多平台发布",
}

/** 授权条目列表（顺序与后端 `ENTITLEMENTS` 一致，便于 UI 稳定排序） */
export const ENTITLEMENTS: readonly LicenseEntitlement[] = Object.freeze([
  "core",
  "ai_cloud",
  "agent",
  "persona",
  "campaign",
  "multi_platform",
])

// ──────────────────────────────────────────────────────────────
// 状态 → 中文标签 / 徽标色调
// ──────────────────────────────────────────────────────────────

/**
 * 徽标色调（语义化，UI 层负责映射到具体 class）：
 *   - muted   未激活（灰）
 *   - success 生效中（主色）
 *   - warning 宽限期（黄）
 *   - danger  已过期 / 无效（红）
 *   - info    尚未生效（蓝）
 */
export type LicenseStatusTone = "muted" | "success" | "warning" | "danger" | "info"

const STATUS_LABELS: Record<LicenseStatus, string> = {
  missing: "未激活",
  active: "生效中",
  grace: "宽限期内",
  expired: "已过期",
  invalid: "无效",
  not_yet_valid: "尚未生效",
}

const STATUS_TONES: Record<LicenseStatus, LicenseStatusTone> = {
  missing: "muted",
  active: "success",
  grace: "warning",
  expired: "danger",
  invalid: "danger",
  not_yet_valid: "info",
}

/** 状态 → 中文标签（未知值返回 "未知"，不抛错） */
export function licenseStatusLabel(status: LicenseStatus | string | undefined | null): string {
  if (!status) return "未知"
  return STATUS_LABELS[status as LicenseStatus] ?? String(status)
}

/** 状态 → 徽标色调（未知值回落到 "muted"） */
export function licenseStatusTone(
  status: LicenseStatus | string | undefined | null,
): LicenseStatusTone {
  if (!status) return "muted"
  return STATUS_TONES[status as LicenseStatus] ?? "muted"
}

/** 判断当前注册码是否为「有效可用」：active / grace / expired 都算曾经激活过；invalid / not_yet_valid / missing 不算 */
export function hasActiveLicense(license: LicenseState | null | undefined): boolean {
  if (!license) return false
  return (
    license.status === "active" ||
    license.status === "grace" ||
    license.status === "expired"
  )
}

// ──────────────────────────────────────────────────────────────
// flag 合并
// ──────────────────────────────────────────────────────────────

/**
 * 合并云端 flags 与后端 `/effective-flags` 结果。
 *
 * 设计约定（**务必保持**）：
 *   - 后端 `/effective-flags` 已经是「注册码授权条目 ∩ 云端订阅配额」的最终交集；
 *   - 前端**不再**做一次交集运算，只做「后端结果优先」的合并展示；
 *   - 无有效注册码（missing / invalid / not_yet_valid）时，后端算出来的
 *     `flags` 是空条目 × 云端 → 全部落到 Community 默认，这与「未激活
 *     的用户本应享受云端订阅」不符，因此**保持云端原值**。
 *
 * 行为：
 *   - 有有效注册码 → `{ ...cloud, ...effective.flags }`（后端结果覆盖云端）
 *   - 无有效注册码 → `{ ...cloud }`（保持云端原值）
 *   - 两个都是空 → `{}`（UI 层用默认占位）
 *
 * 注意：本函数**不会**做交集运算，也**不会**过滤未知 flag key。
 */
export function mergeLicenseFlags(
  cloudFlags: LicenseFlagMap | null | undefined,
  effectiveFlags: LicenseEffectiveFlagsResponse | null | undefined,
): LicenseFlagMap {
  const cloud: LicenseFlagMap = { ...(cloudFlags ?? {}) }
  const license = effectiveFlags?.license
  if (!effectiveFlags || !hasActiveLicense(license)) {
    return cloud
  }
  return { ...cloud, ...effectiveFlags.flags }
}
