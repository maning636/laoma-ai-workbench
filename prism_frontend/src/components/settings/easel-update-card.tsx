"use client"

import { useCallback, useEffect, useState } from "react"
import {
  ArrowDownToLine,
  Check,
  CircleAlert,
  ChevronDown,
  Clock,
  GitCommitHorizontal,
  Loader2,
  RefreshCw,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { useToast } from "@/components/ui/use-toast"
import { API_ENDPOINTS } from "@/lib/env"
import { cn } from "@/lib/utils"

type EaselUpdateState = {
  updating?: boolean
  last_checked_at?: string | null
  last_updated_at?: string | null
  update_available?: boolean
  local_revision?: string | null
  remote_revision?: string | null
  last_error?: string | null
}

type EaselUpdateSettings = {
  enabled?: boolean
  interval_hours?: number | null
  branch?: string | null
  auto_apply?: boolean
}

type EaselUpdateStatus = {
  state?: EaselUpdateState | null
  settings?: EaselUpdateSettings | null
}

type UpdateBadgeState = "checking" | "error" | "updating" | "available" | "latest"

function UpdateBadge({ state }: { state: UpdateBadgeState }) {
  if (state === "checking") {
    return (
      <Badge variant="outline" className="border-border/70 bg-card text-muted-foreground">
        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
        检查中
      </Badge>
    )
  }
  if (state === "error") {
    return (
      <Badge variant="destructive">
        <CircleAlert className="mr-1 h-3 w-3" />
        错误
      </Badge>
    )
  }
  if (state === "updating") {
    return (
      <Badge variant="outline" className="border-border/80 bg-popover text-foreground">
        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
        更新中
      </Badge>
    )
  }
  if (state === "available") {
    return (
      <Badge variant="secondary">
        <ArrowDownToLine className="mr-1 h-3 w-3" />
        有更新
      </Badge>
    )
  }
  return (
    <Badge variant="default">
      <Check className="mr-1 h-3 w-3" />
      最新
    </Badge>
  )
}

function formatTimestamp(value?: string | null) {
  if (!value) return "从未"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function EaselUpdateCard() {
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<EaselUpdateStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)

  const loadStatus = useCallback(async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_ENDPOINTS.base}/api/v1/agent/easel/update/status`, {
        cache: "no-store",
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload?.detail || payload?.error || "Easel 更新状态读取失败")
      }
      setStatus((payload?.data || null) as EaselUpdateStatus | null)
    } catch (error) {
      console.error("Failed to load Easel update status:", error)
      toast({
        title: "Easel 更新状态读取失败",
        description: error instanceof Error ? error.message : "无法读取 Easel 上游更新状态。",
        variant: "destructive",
      })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  const runCheck = useCallback(async () => {
    setChecking(true)
    try {
      const response = await fetch(`${API_ENDPOINTS.base}/api/v1/agent/easel/update/check`, {
        method: "POST",
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload?.success === false) {
        throw new Error(payload?.detail || payload?.error || payload?.data?.message || "检查更新失败")
      }
      toast({
        title: "Easel 更新检查完成",
        description: payload?.data?.message || "已向上游发起一次只读检查。",
      })
      await loadStatus()
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      toast({
        title: "检查更新失败",
        description: message,
        variant: "destructive",
      })
    } finally {
      setChecking(false)
    }
  }, [loadStatus, toast])

  const updateState: EaselUpdateState | null = status?.state || null

  const badgeState: UpdateBadgeState = loading
    ? "checking"
    : updateState?.last_error
      ? "error"
      : updateState?.updating
        ? "updating"
        : updateState?.update_available
          ? "available"
          : "latest"

  const localRevision = updateState?.local_revision
  const remoteRevision = updateState?.remote_revision
  const showError = Boolean(updateState?.last_error)

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <Card className="border-border/70 bg-card">
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full items-start justify-between gap-4 rounded-2xl px-5 py-4 text-left transition-colors hover:bg-accent/40"
          >
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <RefreshCw className="h-4 w-4 text-foreground/70" />
                  Easel 上游更新
                </div>
                <UpdateBadge state={badgeState} />
              </div>
              <p className="text-xs leading-5 text-muted-foreground">
                仅展示 Easel 上游更新状态并支持触发只读检查；本卡片不修改本地版本。
              </p>
            </div>
            <ChevronDown
              className={cn(
                "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                open && "rotate-180"
              )}
            />
          </button>
        </CollapsibleTrigger>

        <CollapsibleContent>
          <CardContent className="space-y-5 border-t border-border/70 pt-5">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-2xl border border-border/70 bg-card/30 p-4">
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-foreground/40">
                  <Clock className="h-3 w-3" />
                  上次检查
                </div>
                <div className="mt-2 text-sm text-foreground/80">
                  {loading ? "检查中..." : formatTimestamp(updateState?.last_checked_at)}
                </div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-card/30 p-4">
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-foreground/40">
                  <ArrowDownToLine className="h-3 w-3" />
                  上次更新
                </div>
                <div className="mt-2 text-sm text-foreground/80">
                  {loading ? "检查中..." : formatTimestamp(updateState?.last_updated_at)}
                </div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-card/30 p-4">
                <div className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-foreground/40">
                  <GitCommitHorizontal className="h-3 w-3" />
                  当前版本
                </div>
                <div className="mt-2 break-all font-mono text-sm text-foreground/80">
                  {loading
                    ? "检查中..."
                    : localRevision
                      ? `${localRevision.slice(0, 8)}${remoteRevision && remoteRevision !== localRevision ? ` → ${remoteRevision.slice(0, 8)}` : ""}`
                      : "未知"}
                </div>
              </div>
            </div>

            {showError && (
              <div className="rounded-2xl border border-destructive/40 bg-destructive/5 p-4">
                <div className="text-xs uppercase tracking-[0.22em] text-destructive/80">错误信息</div>
                <div className="mt-2 break-all text-sm text-destructive">
                  {updateState?.last_error || "未知错误"}
                </div>
              </div>
            )}

            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                className="bg-muted"
                onClick={() => void runCheck()}
                disabled={checking || loading}
              >
                {checking ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                检查更新
              </Button>
              <Button
                variant="secondary"
                className="bg-muted"
                onClick={() => void loadStatus()}
                disabled={loading || checking}
              >
                {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                刷新状态
              </Button>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
