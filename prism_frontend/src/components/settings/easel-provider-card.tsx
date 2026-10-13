"use client"

import { useCallback, useEffect, useState } from "react"
import {
  Check,
  CircleAlert,
  CircleDashed,
  ChevronDown,
  FolderClosed,
  Loader2,
  Palette,
  RefreshCw,
} from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { useToast } from "@/components/ui/use-toast"
import { API_ENDPOINTS } from "@/lib/env"
import { cn } from "@/lib/utils"

type EaselStatus = {
  running?: boolean
  installed?: boolean
  dir?: string | null
  web_api_online?: boolean
  gateway_online?: boolean
  gateway_port?: number | null
  port?: number | null
  url?: string | null
  skills_dir?: string | null
  pid?: number | null
}

type StatusBadgeState = "ready" | "not-running" | "missing" | "checking"

function StatusBadge({ state }: { state: StatusBadgeState }) {
  if (state === "ready") {
    return (
      <Badge variant="default">
        <Check className="mr-1 h-3 w-3" />
        已就绪
      </Badge>
    )
  }
  if (state === "not-running") {
    return (
      <Badge variant="secondary">
        <CircleDashed className="mr-1 h-3 w-3" />
        已安装未运行
      </Badge>
    )
  }
  if (state === "missing") {
    return (
      <Badge variant="destructive">
        <CircleAlert className="mr-1 h-3 w-3" />
        未安装
      </Badge>
    )
  }  return (
    <Badge variant="outline" className="border-border/70 bg-card text-muted-foreground">
      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
      检查中
    </Badge>
  )
}

export function EaselProviderCard() {
  const { toast } = useToast()
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<EaselStatus | null>(null)
  const [loading, setLoading] = useState(true)

  const loadStatus = useCallback(async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_ENDPOINTS.base}/api/v1/agent/easel/status`, {
        cache: "no-store",
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload?.detail || payload?.error || "Easel 状态读取失败")
      }
      setStatus((payload?.data || null) as EaselStatus | null)
    } catch (error) {
      console.error("Failed to load Easel status:", error)
      toast({
        title: "Easel 状态读取失败",
        description: error instanceof Error ? error.message : "无法读取 Easel 工作台状态。",
        variant: "destructive",
      })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void loadStatus()
  }, [loadStatus])

  const badgeState: StatusBadgeState = loading
    ? "checking"
    : !status
      ? "checking"
      : status.installed && status.web_api_online
        ? "ready"
        : !status.installed
          ? "missing"
          : "not-running"

  const summaryDir = status?.dir || "-"
  const summaryUrl = status?.web_api_online ? (status?.url || "未运行") : "未运行"
  const summaryGateway = status?.gateway_online
    ? `OK (${status?.gateway_port ?? "-"})`
    : "未启动"
  const skillsDir = status?.skills_dir || "未检测到"

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
                  <Palette className="h-4 w-4 text-foreground/70" />
                  Easel 工作台
                </div>
                <StatusBadge state={badgeState} />
              </div>
              <p className="text-xs leading-5 text-muted-foreground">
                Easel Web 工作台与 Gateway 的运行状态，仅只读展示，不修改路径或配置。
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
                  <FolderClosed className="h-3 w-3" />
                  Easel 目录
                </div>
                <div className="mt-2 break-all font-mono text-xs text-foreground/80">
                  {loading ? "检查中..." : summaryDir}
                </div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-card/30 p-4">
                <div className="text-xs uppercase tracking-[0.22em] text-foreground/40">Web URL</div>
                <div className="mt-2 break-all font-mono text-xs text-foreground/80">
                  {loading ? "检查中..." : summaryUrl}
                </div>
              </div>
              <div className="rounded-2xl border border-border/70 bg-card/30 p-4">
                <div className="text-xs uppercase tracking-[0.22em] text-foreground/40">Gateway</div>
                <div className="mt-2 break-all font-mono text-xs text-foreground/80">
                  {loading ? "检查中..." : summaryGateway}
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-border/70 bg-card/30 p-4">
              <div className="text-xs uppercase tracking-[0.22em] text-foreground/40">Skills 根目录</div>
              <div className="mt-2 break-all font-mono text-xs text-foreground/80">
                {loading ? "检查中..." : skillsDir}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button
                variant="secondary"
                className="bg-muted"
                onClick={() => void loadStatus()}
                disabled={loading}
              >
                {loading ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                刷新
              </Button>
            </div>
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}
