/**
 * Open Core · Plan Badge（Community / Pro 套餐徽标）。
 *
 * 位置：侧边栏底部（`sidebar-new.tsx`）。
 *
 * 行为：
 *   1. 挂载时调用 `GET /cloud/feature-flags`（复用 `gatewayRequest`，自动注入 JWT）；
 *   2. 云端不可达 / 未登录 / 401 / 网络错误 → **默认显示 Community**（不阻断 UI）；
 *   3. 组件提供 4 秒轮询（低频，不干扰用户），失败静默。
 *
 * 视觉：
 *   - Community：灰色 badge + "3 账号 / 3 平台" + "升级 Pro" 按钮
 *   - Pro：金色/primary badge + "无限账号 / 8 平台" + "续费" 按钮
 *
 * 复用：
 *   - `@/components/ui/badge` / `@/components/ui/button` / `@/components/ui/progress`
 *   - `@/lib/gatewayRequest`（feature="billing" 走云端）
 *   - `@/lib/plan-flags` 纯逻辑（`normalizeFlags` / `buildPlanBadgeView`）
 */
"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import Link from "next/link"
import {
  Crown,
  ChevronRight,
  Infinity as InfinityIcon,
  RefreshCw,
  Sparkles,
} from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cloudAuth } from "@/lib/cloud-auth"
import { gatewayRequest } from "@/lib/client-gateway"
import {
  buildPlanBadgeView,
  normalizeFlags,
  type FeatureFlagsResponse,
  type PlanBadgeView,
} from "@/lib/plan-flags"

const FLAGS_PATH = "billing/feature-flags"
const POLL_INTERVAL_MS = 4 * 60 * 1000

interface PlanBadgeProps {
  /** 侧边栏 collapsed 时显示图标版 */
  collapsed?: boolean
  /** 覆盖升级 URL（测试/多环境） */
  upgradeUrl?: string
  className?: string
}

/**
 * 拉取 feature flags 并归一化；任何失败都返回 `DEFAULT_COMMUNITY_FLAGS`，
 * 保证云端不可达时 UI 不阻断。
 */
async function fetchFlags(): Promise<FeatureFlagsResponse> {
  try {
    const token = await cloudAuth.getAccessToken()
    const r = await gatewayRequest<FeatureFlagsResponse>({
      feature: "billing",
      path: FLAGS_PATH,
      method: "GET",
      needToken: Boolean(token),
      token: token || "",
      timeoutMs: 5000,
    })
    if (r.ok && r.data) {
      return normalizeFlags(r.data)
    }
  } catch (e) {
    // 网络/JSON/超时/未登录 —— 全部静默回落到 Community
    if (process.env.NODE_ENV === "development") {
      console.warn("[PlanBadge] feature-flags fetch failed, fallback community:", e)
    }
  }
  return normalizeFlags({ plan: "community", flags: {} })
}

/**
 * 渲染配额数字：`-1` 显示 Infinity 图标；`0` 显示 0 并标"锁"。
 */
function QuotaCell({
  label,
  value,
  locked,
}: {
  label: string
  value: string
  locked: boolean
}) {
  return (
    <div
      className="flex flex-col items-center px-1.5 py-0.5"
      title={locked ? `${label}：升级 Pro 解锁` : label}
    >
      <span className="flex items-center gap-0.5 text-xs font-semibold tabular-nums text-foreground">
        {value === "无限" ? (
          <InfinityIcon className="h-3 w-3 text-primary" />
        ) : (
          value
        )}
      </span>
      <span className="text-[9px] uppercase tracking-wider text-foreground/50">
        {label}
      </span>
    </div>
  )
}

export function PlanBadge({
  collapsed = false,
  upgradeUrl,
  className,
}: PlanBadgeProps) {
  const [flags, setFlags] = useState<FeatureFlagsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const mountedRef = useRef(true)

  const load = useCallback(async (opts: { silent?: boolean } = {}) => {
    if (!opts.silent) {
      setRefreshing(true)
    }
    try {
      const next = await fetchFlags()
      if (mountedRef.current) setFlags(next)
    } finally {
      if (mountedRef.current) {
        setLoading(false)
        setRefreshing(false)
      }
    }
  }, [])

  useEffect(() => {
    mountedRef.current = true
    void load()
    const id = window.setInterval(() => void load({ silent: true }), POLL_INTERVAL_MS)
    return () => {
      mountedRef.current = false
      window.clearInterval(id)
    }
  }, [load])

  const view: PlanBadgeView | null = flags
    ? buildPlanBadgeView(flags, { upgradeUrl })
    : null

  // ── 骨架屏：仅首次加载时显示，之后一直展示 Community 默认 ──
  if (!view) {
    return (
      <div
        className={`flex items-center justify-center rounded-xl border border-border/60 bg-background/40 py-2 text-xs text-muted-foreground ${className || ""}`}
        aria-busy="true"
        aria-label="加载套餐信息"
      >
        <RefreshCw className="h-3.5 w-3.5 animate-spin" />
      </div>
    )
  }

  const lockedAgent = view.plan === "community" && view.agentQuota === 0

  // ── collapsed 模式：只显示一个小徽标 ──
  if (collapsed) {
    return (
      <Link
        href={view.upgradeUrl}
        className={`flex h-10 w-10 items-center justify-center rounded-xl border ${
          view.isPro
            ? "border-primary/40 bg-primary/15 text-primary"
            : "border-border/60 bg-background/40 text-foreground/70 hover:bg-accent"
        }`}
        title={view.isPro ? "Pro 会员" : "Community 免费版，点击升级 Pro"}
        aria-label={view.isPro ? "Pro 会员" : "Community 免费版，升级 Pro"}
      >
        {view.isPro ? (
          <Crown className="h-4 w-4" />
        ) : (
          <Sparkles className="h-4 w-4" />
        )}
      </Link>
    )
  }

  return (
    <div
      className={`rounded-xl border p-2.5 space-y-2 ${
        view.isPro
          ? "border-primary/40 bg-gradient-to-br from-primary/10 via-background to-background"
          : "border-border/60 bg-background/40"
      } ${className || ""}`}
      role="group"
      aria-label={view.isPro ? "Pro 会员" : "Community 免费版"}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 min-w-0">
          {view.isPro ? (
            <Crown className="h-3.5 w-3.5 shrink-0 text-primary" />
          ) : (
            <Sparkles className="h-3.5 w-3.5 shrink-0 text-foreground/60" />
          )}
          <Badge
            variant="outline"
            className={`text-[10px] uppercase tracking-wider ${
              view.isPro
                ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
                : "border-border/60 bg-muted/40 text-foreground/70 hover:bg-muted/70"
            }`}
          >
            {view.isPro ? "Pro" : "Community"}
          </Badge>
        </div>
        <Button
          size="icon"
          variant="ghost"
          className="h-6 w-6 text-foreground/50 hover:text-foreground"
          onClick={() => void load()}
          disabled={refreshing}
          aria-label="刷新套餐信息"
          title="刷新套餐信息"
        >
          <RefreshCw className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`} />
        </Button>
      </div>

      <div className="grid grid-cols-3 divide-x divide-border/60 rounded-lg border border-border/50 bg-background/60 py-1">
        <QuotaCell label="账号" value={view.accountsLabel} locked={false} />
        <QuotaCell label="平台" value={view.platformsLabel} locked={false} />
        <QuotaCell label="智能体" value={view.agentLabel} locked={lockedAgent} />
      </div>

      <Link
        href={view.upgradeUrl}
        className="group flex items-center justify-between gap-2 rounded-lg border border-primary/40 bg-primary/10 px-2.5 py-1.5 text-xs font-medium text-primary hover:bg-primary hover:text-background transition-colors"
      >
        <span>{view.actionLabel}</span>
        <ChevronRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" />
      </Link>
    </div>
  )
}

export default PlanBadge
