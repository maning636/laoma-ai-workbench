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
 * 客户端订阅心跳 hook。
 *
 * 行为:
 *   - 组件挂载后立即校验一次(仅在已登录时)
 *   - 之后每 `LICENSE_HEARTBEAT_INTERVAL_MS`(24h)校验一次
 *   - 手动 refresh 接口供 settings 页触发
 *
 * 结果:
 *   - `status`: 云端返回的订阅状态;未登录或网络失败时给出降级对象
 *   - `error`:  最近一次心跳的错误描述(若有)
 *   - `refreshing`: 心跳请求 in-flight 标记
 */
export function useLicenseHeartbeat(
  intervalMs: number = LICENSE_HEARTBEAT_INTERVAL_MS,
  enabled: boolean = true,
): LicenseHeartbeatResult {
  const [status, setStatus] = useState<SubscriptionStatus | null>(null)
  const [lastCheckedAt, setLastCheckedAt] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
      }, intervalMs)
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
  }, [enabled, intervalMs, runCheck])

  return { status, lastCheckedAt, error, refreshing, refresh: runCheck }}
