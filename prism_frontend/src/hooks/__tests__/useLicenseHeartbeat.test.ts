import { describe, expect, it } from "vitest"

import { parseHeartbeatIntervalMs } from "../useLicenseHeartbeat"

// ──────────────────────────────────────────────────────────────
// F-F(F7): 心跳单位换算边界修正。
//
// 旧规则:"无单位数字 < 1000 → 秒 / ≥ 1000 → 毫秒",导致
//   "999"  = 999s (秒)
//   "1000" = 1s   (毫秒)
// 1000ms 的临界跳变。
//
// 新规则:无单位数字字符串**一律按秒解释**。
//   - 需要毫秒:用原生 number 传参,或显式带单位字符串(不推荐 3600000,用 "1h")
//   - 带单位的 "30m" / "2h" / "1d" / "60s" 保持不变
// ──────────────────────────────────────────────────────────────

const FALLBACK = 86_400_000 // 24h

describe("parseHeartbeatIntervalMs / F-F(F7) 单位换算", () => {
  it("无单位数字 '999' → 999s = 999000ms", () => {
    expect(parseHeartbeatIntervalMs("999", FALLBACK)).toBe(999_000)
  })

  it("无单位数字 '1000' → 1000s = 1000000ms(不再退化为 1s)", () => {
    expect(parseHeartbeatIntervalMs("1000", FALLBACK)).toBe(1_000_000)
  })

  it("'3600' → 3600s = 1h", () => {
    expect(parseHeartbeatIntervalMs("3600", FALLBACK)).toBe(3_600_000)
  })

  it("'30m' → 30 分钟", () => {
    expect(parseHeartbeatIntervalMs("30m", FALLBACK)).toBe(30 * 60 * 1000)
  })

  it("'2h' → 2 小时", () => {
    expect(parseHeartbeatIntervalMs("2h", FALLBACK)).toBe(2 * 60 * 60 * 1000)
  })

  it("'1d' → 24 小时", () => {
    expect(parseHeartbeatIntervalMs("1d", FALLBACK)).toBe(24 * 60 * 60 * 1000)
  })

  it("'60s' → 60 秒", () => {
    expect(parseHeartbeatIntervalMs("60s", FALLBACK)).toBe(60 * 1000)
  })

  it("小写 '30M' 也接受(与 '30m' 等价)", () => {
    expect(parseHeartbeatIntervalMs("30M", FALLBACK)).toBe(30 * 60 * 1000)
  })

  it("带空格 '2 h' 也接受", () => {
    expect(parseHeartbeatIntervalMs("  2 h  ", FALLBACK)).toBe(2 * 60 * 60 * 1000)
  })

  it("原生 number 直接当毫秒(不 ×1000)", () => {
    expect(parseHeartbeatIntervalMs(3600, FALLBACK)).toBe(3600)
    expect(parseHeartbeatIntervalMs(24 * 60 * 60 * 1000, FALLBACK)).toBe(86_400_000)
  })

  // ── 非法值 → fallback ──

  it("空字符串 / 非字符串 → fallback", () => {
    expect(parseHeartbeatIntervalMs("", FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs(null, FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs(undefined, FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs({}, FALLBACK)).toBe(FALLBACK)
  })

  it("非数字字符串 → fallback", () => {
    expect(parseHeartbeatIntervalMs("abc", FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs("1x", FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs("1h30m", FALLBACK)).toBe(FALLBACK)
  })

  it("数字为 0 或负数 → fallback", () => {
    expect(parseHeartbeatIntervalMs("0", FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs("-1", FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs("0s", FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs(0, FALLBACK)).toBe(FALLBACK)
    expect(parseHeartbeatIntervalMs(-1, FALLBACK)).toBe(FALLBACK)
  })

  it("带未知单位 → fallback", () => {
    // "w" 未定义
    expect(parseHeartbeatIntervalMs("3w", FALLBACK)).toBe(FALLBACK)
  })

  it("边界:'1' → 1s(=1000ms),不再退化为 1ms", () => {
    expect(parseHeartbeatIntervalMs("1", FALLBACK)).toBe(1000)
  })
})
