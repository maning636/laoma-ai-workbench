"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  cloudAuth,
  LICENSE_HEARTBEAT_INTERVAL_MS,
  type SubscriptionStatus,
} from "@/lib/cloud-auth"

export interface LicenseHeartbeatResult {
  status: SubscriptionStatus | null
  lastCheckedAt: number | null
  error: string | null
  refreshing: boolean
  refresh: () => Promise<void>
}

/**
 * 解析心跳间隔:优先级 参数 > env > 默认 24h。
 *
 * `NEXT_PUBLIC_LICENSE_HEARTBEAT_MS` 由构建期注入(浏览器可见,
 * 不需要 NEXT_PUBLIC 前缀的私有变量在浏览器里不可用)。
 * 允许:
 *   - 数字字符串(毫秒)
 *   - 秒字符串 `"3600"` → 视为秒,自动 ×1000
 *   - 分钟字符串 `"30m"` / 小时 `"2h"` / 天 `"1d"`
 * 解析失败或缺失 → 回落 `fallback`。
 */
function parseHeartbeatIntervalMs(raw: unknown, fallback: number): number {
  if (typeof raw === "number" && Number.isFinite(raw) && raw > 0) {
    return Math.floor(raw)
  }
  if (typeof raw !== "string") return fallback
  const s = raw.trim()
  if (!s) return fallback

  // 单位后缀
  const m = s.match(/^(\d+(?:\.\d+)?)\s*([smhd])?$/i)
  if (!m) {
    // 无单位:数字 < 1000 视为秒,否则毫秒(与常见约定兼容)
    const n = Number(s)
    if (!Number.isFinite(n) || n <= 0) return fallback
    return Math.floor(n < 1000 ? n * 1000 : n)
  }
  const num = parseFloat(m[1])
  if (!Number.isFinite(num) || num <= 0) return fallback
  const unit = m[2].toLowerCase()
  if (unit === "s") return Math.floor(num * 1000)
  if (unit === "m") return Math.floor(num * 60 * 1000)
  if (unit === "h") return Math.floor(num * 60 * 60 * 1000)
  if (unit === "d") return Math.floor(num * 24 * 60 * 60 * 1000)
  return fallback
}

/** 读 env,仅浏览器/服务端安全(用 `process.env` 兼容 Next.js)。 */
function envHeartbeatIntervalMs(fallback: number): number {
  const raw =
    typeof process !== "undefined" && process.env
      ? process.env.NEXT_PUBLIC_LICENSE_HEARTBEAT_MS
      : undefined
  return parseHeartbeatIntervalMs(raw, fallback)
}

/**
 * 客户端订阅心跳 hook。
 *
 * 行为:
 *   - 组件挂载后立即校验一次(仅在已登录时)
 *   - 之后按 intervalMs 校验一次(默认 24h)
 *   - 手动 refresh 接口供 settings 页触发
 *
 * intervalMs 优先级:
 *   1. 参数(运行时传入)
 *   2. env `NEXT_PUBLIC_LICENSE_HEARTBEAT_MS`
 *      - 支持数字(毫秒,或数字 < 1000 视为秒)
 *      - 支持 `"30m"` / `"2h"` / `"1d"` 单位后缀
 *   3. `cloud-auth.LICENSE_HEARTBEAT_INTERVAL_MS`(默认 24h)
 *
 * 结果:
 *   - `status`: 云端返回的订阅状态;未登录或网络失败时给出降级对象
 *   - `error`:  最近一次心跳的错误描述(若有)
 *   - `refreshing`: 心跳请求 in-flight 标记
 */
export function useLicenseHeartbeat(
  intervalMs: number | undefined = undefined,
  enabled: boolean = true,
): LicenseHeartbeatResult {
  const [status, setStatus] = useState<SubscriptionStatus | null>(null)
  const [lastCheckedAt, setLastCheckedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 惰性解析:参数 > env > 默认。env 是构建期常量,直接算即可(幂等)。
  const effectiveIntervalMs =
    intervalMs ?? envHeartbeatIntervalMs(LICENSE_HEARTBEAT_INTERVAL_MS)

  const runCheck = useCallback(async () => {
    setRefreshing(true)
    setError(null)
    try {
      const pair = await cloudAuth.getCurrentTokenPair()
      if (!pair) {
        // 未登录:给一个明确的 "unauthenticated" 状态,避免 UI 显示 "加载中"
        setStatus({
          valid: false,
          reason: "unauthenticated",
          plan: "",
          status: "",
          expire_at: null,
          quota: 0,
          used: 0,
          remaining: 0,
          is_pro: false,
        })
      } else {
        const result = await cloudAuth.verifyLicense()
        setStatus(result)
      }
      setLastCheckedAt(Date.now())
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(msg)
    } finally {
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    const scheduleNext = () => {
      timer = setTimeout(async () => {
        if (cancelled) return
        await runCheck()
        scheduleNext()
      }, effectiveIntervalMs)
    }

    ;(async () => {
      if (cancelled) return
      await runCheck()
      if (cancelled) return
      scheduleNext()
    })()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [enabled, effectiveIntervalMs, runCheck])

  return { status, lastCheckedAt, error, refreshing, refresh: runCheck }}
