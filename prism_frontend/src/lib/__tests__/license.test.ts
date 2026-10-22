/**
 * 注册码（license）lib 单元测试。
 *
 * 覆盖范围：
 *   - LICENSE_FLAG_NAMES / ENTITLEMENTS / ENTITLEMENT_LABELS 常量正确
 *   - licenseStatusLabel / licenseStatusTone 对 6 种状态返回预期值
 *   - mergeLicenseFlags 行为：后端结果优先；无 license 时保持云端原值
 */
import { describe, expect, it } from "vitest"
import {
  ENTITLEMENTS,
  ENTITLEMENT_LABELS,
  LICENSE_FLAG_NAMES,
  hasActiveLicense,
  licenseStatusLabel,
  licenseStatusTone,
  mergeLicenseFlags,
  type LicenseEffectiveFlagsResponse,
  type LicenseState,
  type LicenseStatus,
} from "../license"

// ============ 常量 ============

describe("LICENSE_FLAG_NAMES", () => {
  it("包含 12 个 flag 名（与后端 FLAG_CAPACITY 对齐）", () => {
    expect(LICENSE_FLAG_NAMES).toHaveLength(12)
  })

  it("覆盖 4 个数值型 + 4 个布尔型 + 2 个模式型 flag", () => {
    // 数值型
    for (const n of ["max_accounts", "max_platforms", "agent_quota", "team_members"]) {
      expect(LICENSE_FLAG_NAMES).toContain(n)
    }
    // 布尔型
    for (const n of [
      "data_recovery",
      "persona",
      "proxy_management",
      "stream_chat",
    ]) {
      expect(LICENSE_FLAG_NAMES).toContain(n)
    }
    // 模式型（ai_mode / image_gen / cloud_prompt / campaign_orchestration 中的 4 项）
    for (const n of ["ai_mode", "image_gen", "cloud_prompt", "campaign_orchestration"]) {
      expect(LICENSE_FLAG_NAMES).toContain(n)
    }
  })

  it("无重复", () => {
    expect(new Set(LICENSE_FLAG_NAMES).size).toBe(LICENSE_FLAG_NAMES.length)
  })
})

describe("ENTITLEMENTS / ENTITLEMENT_LABELS", () => {
  it("6 个条目中文名一一对应", () => {
    expect(ENTITLEMENTS).toHaveLength(6)
    for (const key of ENTITLEMENTS) {
      expect(ENTITLEMENT_LABELS[key]).toBeDefined()
    }
  })

  it("与产品文档一致的中文名", () => {
    expect(ENTITLEMENT_LABELS.core).toBe("基础包")
    expect(ENTITLEMENT_LABELS.ai_cloud).toBe("云端 AI")
    expect(ENTITLEMENT_LABELS.agent).toBe("Agent 配额")
    expect(ENTITLEMENT_LABELS.persona).toBe("Persona 与代理")
    expect(ENTITLEMENT_LABELS.campaign).toBe("营销活动编排")
    expect(ENTITLEMENT_LABELS.multi_platform).toBe("多平台发布")
  })
})

// ============ 状态映射 ============

describe("licenseStatusLabel", () => {
  it("对 6 种状态都返回预期中文标签", () => {
    expect(licenseStatusLabel("missing")).toBe("未激活")
    expect(licenseStatusLabel("active")).toBe("生效中")
    expect(licenseStatusLabel("grace")).toBe("宽限期内")
    expect(licenseStatusLabel("expired")).toBe("已过期")
    expect(licenseStatusLabel("invalid")).toBe("无效")
    expect(licenseStatusLabel("not_yet_valid")).toBe("尚未生效")
  })

  it("未知值回落到 '未知'", () => {
    expect(licenseStatusLabel(undefined)).toBe("未知")
    expect(licenseStatusLabel(null)).toBe("未知")
    expect(licenseStatusLabel("")).toBe("未知")
    expect(licenseStatusLabel("unknown_value")).toBe("unknown_value")
  })
})

describe("licenseStatusTone", () => {
  it("对 6 种状态返回语义化色调", () => {
    expect(licenseStatusTone("missing")).toBe("muted")
    expect(licenseStatusTone("active")).toBe("success")
    expect(licenseStatusTone("grace")).toBe("warning")
    expect(licenseStatusTone("expired")).toBe("danger")
    expect(licenseStatusTone("invalid")).toBe("danger")
    expect(licenseStatusTone("not_yet_valid")).toBe("info")
  })

  it("未知值回落到 'muted'", () => {
    expect(licenseStatusTone(undefined)).toBe("muted")
    expect(licenseStatusTone(null)).toBe("muted")
    expect(licenseStatusTone("foo")).toBe("muted")
  })
})

describe("hasActiveLicense", () => {
  it("active / grace / expired 均视为 '曾经激活过'", () => {
    for (const s of ["active", "grace", "expired"] as const) {
      expect(hasActiveLicense(makeLicense(s))).toBe(true)
    }
  })

  it("missing / invalid / not_yet_valid 均视为未激活", () => {
    for (const s of ["missing", "invalid", "not_yet_valid"] as const) {
      expect(hasActiveLicense(makeLicense(s))).toBe(false)
    }
    expect(hasActiveLicense(null)).toBe(false)
    expect(hasActiveLicense(undefined)).toBe(false)
  })
})

// ============ 合并 ============

describe("mergeLicenseFlags", () => {
  it("无 license（missing）：保持云端原值", () => {
    const cloud = { max_accounts: 3, max_platforms: 3 }
    const eff = makeEffective({ status: "missing" }, { max_accounts: 0, max_platforms: 0 })
    const merged = mergeLicenseFlags(cloud, eff)
    expect(merged.max_accounts).toBe(3)
    expect(merged.max_platforms).toBe(3)
  })

  it("invalid license：保持云端原值", () => {
    const cloud = { max_accounts: 3, max_platforms: 3 }
    const eff = makeEffective({ status: "invalid" }, { max_accounts: 0 })
    const merged = mergeLicenseFlags(cloud, eff)
    expect(merged.max_accounts).toBe(3)
  })

  it("not_yet_valid license：保持云端原值", () => {
    const cloud = { max_accounts: 3, max_platforms: 3 }
    const eff = makeEffective({ status: "not_yet_valid" }, { max_accounts: 0 })
    const merged = mergeLicenseFlags(cloud, eff)
    expect(merged.max_accounts).toBe(3)
  })

  it("active license：后端结果优先，覆盖云端", () => {
    const cloud = { max_accounts: 3, max_platforms: 3, agent_quota: 0 }
    const eff = makeEffective(
      { status: "active", entitlements: ["core", "multi_platform", "agent"] },
      { max_accounts: -1, max_platforms: 8, agent_quota: 2 },
    )
    const merged = mergeLicenseFlags(cloud, eff)
    expect(merged.max_accounts).toBe(-1)
    expect(merged.max_platforms).toBe(8)
    expect(merged.agent_quota).toBe(2)
  })

  it("grace license：后端结果优先（宽限期内仍能读最终 flag）", () => {
    const cloud = { max_accounts: 3 }
    const eff = makeEffective({ status: "grace" }, { max_accounts: -1 })
    const merged = mergeLicenseFlags(cloud, eff)
    expect(merged.max_accounts).toBe(-1)
  })

  it("expired license：后端结果优先（只读但 flag 仍反映授权）", () => {
    const cloud = { max_accounts: 3 }
    const eff = makeEffective({ status: "expired" }, { max_accounts: -1 })
    const merged = mergeLicenseFlags(cloud, eff)
    expect(merged.max_accounts).toBe(-1)
  })

  it("effectiveFlags 为空：回落到云端", () => {
    const cloud = { max_accounts: 3 }
    expect(mergeLicenseFlags(cloud, null)).toEqual({ max_accounts: 3 })
    expect(mergeLicenseFlags(cloud, undefined)).toEqual({ max_accounts: 3 })
  })

  it("两个都为空：返回空对象", () => {
    expect(mergeLicenseFlags(null, null)).toEqual({})
    expect(mergeLicenseFlags(undefined, undefined)).toEqual({})
  })
})

// ============ 工具函数 ============

function makeLicense(
  status: LicenseStatus,
  overrides: Partial<LicenseState> = {},
): LicenseState {
  return {
    status,
    valid: status !== "missing",
    entitlements: [],
    expiresAt: null,
    graceDays: 7,
    readOnly: false,
    licenseId: null,
    customer: null,
    message: "",
    hasToken: status !== "missing",
    ...overrides,
  }
}

/** 构造一个后端 `/effective-flags` 响应（license 可以是 partial，会补齐默认值） */
function makeEffective(
  license: Partial<LicenseState> & { status: LicenseStatus },
  flags: Record<string, number | boolean | string>,
): LicenseEffectiveFlagsResponse {
  return {
    flags,
    license: makeLicense(license.status, license),
    readOnly: license.readOnly ?? false,
    cloudAvailable: true,
  }
}
