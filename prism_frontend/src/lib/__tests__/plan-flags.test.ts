import { describe, expect, it } from "vitest"
import {
  FEATURE_NAMES,
  DEFAULT_COMMUNITY_FLAGS,
  DEFAULT_UPGRADE_URL,
  buildPlanBadgeView,
  formatLimit,
  isFeatureAllowed,
  normalizeFlags,
  type FeatureFlagsResponse,
} from "../plan-flags"

describe("FEATURE_NAMES", () => {
  it("包含 Open Core 报告的 10 项 flag", () => {
    expect(FEATURE_NAMES).toHaveLength(10)
  })

  it("包含关键 4 个数值型 feature", () => {
    for (const name of ["max_accounts", "max_platforms", "agent_quota", "team_members"]) {
      expect(FEATURE_NAMES).toContain(name)
    }
  })

  it("无重复", () => {
    expect(new Set(FEATURE_NAMES).size).toBe(FEATURE_NAMES.length)
  })
})

describe("DEFAULT_COMMUNITY_FLAGS", () => {
  it("所有 FEATURE_NAMES 都有默认值", () => {
    for (const name of FEATURE_NAMES) {
      expect(DEFAULT_COMMUNITY_FLAGS[name]).toBeDefined()
    }
  })

  it("Community 默认：3 账号 / 3 平台 / 0 智能体", () => {
    expect(DEFAULT_COMMUNITY_FLAGS.max_accounts).toBe(3)
    expect(DEFAULT_COMMUNITY_FLAGS.max_platforms).toBe(3)
    expect(DEFAULT_COMMUNITY_FLAGS.agent_quota).toBe(0)
  })
})

describe("formatLimit", () => {
  it("-1 → 无限", () => {
    expect(formatLimit(-1)).toBe("无限")
  })

  it("普通数字 → 字符串", () => {
    expect(formatLimit(3)).toBe("3")
    expect(formatLimit(0)).toBe("0")
  })

  it("字符串原样返回", () => {
    expect(formatLimit("cloud")).toBe("cloud")
  })

  it("空值 → 占位符", () => {
    expect(formatLimit(null)).toBe("—")
    expect(formatLimit(undefined)).toBe("—")
    expect(formatLimit("")).toBe("—")
  })
})

describe("normalizeFlags", () => {
  it("pro plan 归一化保留", () => {
    const r = normalizeFlags({
      plan: "pro",
      flags: { max_accounts: -1, max_platforms: 8, agent_quota: 2 },
    })
    expect(r.plan).toBe("pro")
    expect(r.flags.max_accounts).toBe(-1)
    expect(r.flags.max_platforms).toBe(8)
    expect(r.flags.agent_quota).toBe(2)
  })

  it("未知 plan 保守回落到 community", () => {
    const r = normalizeFlags({ plan: "team" as any, flags: {} })
    expect(r.plan).toBe("community")
  })

  it("空响应 → 默认 community", () => {
    const r = normalizeFlags(null)
    expect(r.plan).toBe("community")
    expect(r.flags.max_accounts).toBe(3)
  })

  it("缺失 flag 补齐到 Community 默认", () => {
    const r = normalizeFlags({ plan: "pro", flags: { max_accounts: -1 } })
    expect(r.plan).toBe("pro")
    expect(r.flags.max_accounts).toBe(-1)
    // 未提供的其他 flag 用 Community 默认补齐
    expect(r.flags.data_recovery).toBe(true) // D7：数据回收社区版即可用
  })

  it("忽略未知 flag key（不在 FEATURE_NAMES 中）", () => {
    const r = normalizeFlags({
      plan: "community",
      flags: { max_accounts: 5, _unknown: 999 },
    })
    expect((r.flags as Record<string, unknown>)._unknown).toBeUndefined()
    expect(r.flags.max_accounts).toBe(5)
  })

  it("忽略非 number/boolean/string 类型的值", () => {
    const r = normalizeFlags({
      plan: "community",
      flags: { max_accounts: {} as any, max_platforms: 8 },
    })
    expect(r.flags.max_accounts).toBe(3) // 回落到默认
    expect(r.flags.max_platforms).toBe(8)
  })
})

describe("buildPlanBadgeView", () => {
  const communityResp: FeatureFlagsResponse = {
    plan: "community",
    flags: {
      max_accounts: 3,
      max_platforms: 3,
      agent_quota: 0,
    },
  }

  it("Community：显示 3/3/0 与'加微信开通'", () => {
    const v = buildPlanBadgeView(communityResp)
    expect(v.plan).toBe("community")
    expect(v.isPro).toBe(false)
    expect(v.accountsLabel).toBe("3")
    expect(v.platformsLabel).toBe("3")
    expect(v.agentLabel).toBe("0")
    expect(v.actionLabel).toBe("加微信开通")
  })

  it("Pro：-1 显示'无限'，actionLabel='续费联系'", () => {
    const v = buildPlanBadgeView({
      plan: "pro",
      flags: { max_accounts: -1, max_platforms: 8, agent_quota: 2 },
    })
    expect(v.isPro).toBe(true)
    expect(v.accountsLabel).toBe("无限")
    expect(v.platformsLabel).toBe("多") // D5：Pro 不写死平台数量
    expect(v.agentLabel).toBe("2")
    expect(v.actionLabel).toBe("续费联系")
  })

  it("upgrade_url 缺失时回落到 DEFAULT_UPGRADE_URL", () => {
    const v = buildPlanBadgeView(communityResp)
    expect(v.upgradeUrl).toBe(DEFAULT_UPGRADE_URL)
  })

  it("upgrade_url 云端提供时优先使用", () => {
    const v = buildPlanBadgeView({ ...communityResp, upgrade_url: "/billing/upgrade" })
    expect(v.upgradeUrl).toBe("/billing/upgrade")
  })

  it("opts.upgradeUrl 优先级最高", () => {
    const v = buildPlanBadgeView(
      { ...communityResp, upgrade_url: "/billing/upgrade" },
      { upgradeUrl: "/custom" },
    )
    expect(v.upgradeUrl).toBe("/custom")
  })

  it("缺失 flag 时数值字段回落到默认", () => {
    const v = buildPlanBadgeView({ plan: "community", flags: {} })
    expect(v.maxAccounts).toBe(3)
    expect(v.maxPlatforms).toBe(3)
    expect(v.agentQuota).toBe(0)
  })
})

describe("isFeatureAllowed", () => {
  it("Community：agent_quota=0 → false", () => {
    expect(isFeatureAllowed({ plan: "community", flags: { agent_quota: 0 } }, "agent_quota")).toBe(false)
  })

  it("Pro：agent_quota=2 → true", () => {
    expect(isFeatureAllowed({ plan: "pro", flags: { agent_quota: 2 } }, "agent_quota")).toBe(true)
  })

  it("布尔型 feature 直接返回", () => {
    expect(isFeatureAllowed({ plan: "community", flags: { persona: false } }, "persona")).toBe(false)
    expect(isFeatureAllowed({ plan: "pro", flags: { persona: true } }, "persona")).toBe(true)
  })

  it("字符串型 feature：非空视为允许", () => {
    expect(isFeatureAllowed({ plan: "community", flags: { ai_mode: "local_key" } }, "ai_mode")).toBe(true)
  })

  it("缺失 feature → false", () => {
    expect(isFeatureAllowed({ plan: "community", flags: {} }, "persona")).toBe(false)
  })

  it("max_accounts=-1（无限）→ true", () => {
    expect(isFeatureAllowed({ plan: "pro", flags: { max_accounts: -1 } }, "max_accounts")).toBe(true)
  })
})
