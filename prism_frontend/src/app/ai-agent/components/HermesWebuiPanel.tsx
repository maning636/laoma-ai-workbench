"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import { CircleAlert, ExternalLink, Loader2, Monitor, RefreshCw, X } from "lucide-react"

import { Button } from "@/components/ui/button"
import { resolveRuntimeBackendBase } from "@/lib/runtime-backend"

// =============================================================
// HermesWebuiPanel
// ------------------------------------------------------------
// 官方 Hermes WebUI（hermes-webui 的 /chat 页面）的可选面板。
// 之前 /hermes-chat 被 AppShell 用硬编码 http://127.0.0.1:9119/chat
// iframe 覆盖，Community 桌面版不带 hermes-webui 运行时 → 永远白屏。
// 现在改成：先读后端运行时状态 GET /api/v1/agent/config/hermes/runtime，
// 拿到真实 dashboard_url 才挂 iframe；没装就明确告诉用户去哪装。
// 原生 SSE 对话（/api/v1/agent/hermes-stream）才是主路径，不依赖任何外部进程。
// =============================================================

type HermesRuntime = {
  agent_installed?: boolean
  official_dashboard_installed?: boolean
  dashboard_running?: boolean
  dashboard_url?: string
  dashboard_port?: number
}

function extractRuntime(payload: unknown): HermesRuntime | null {
  if (!payload || typeof payload !== "object") return null
  const data = (payload as { data?: HermesRuntime | { runtime?: HermesRuntime } }).data
  if (!data || typeof data !== "object") return null
  if ("runtime" in data && data.runtime && typeof data.runtime === "object") {
    return data.runtime
  }
  return data as HermesRuntime
}

export function HermesWebuiPanel({ onClose }: { onClose: () => void }) {
  const [runtime, setRuntime] = useState<HermesRuntime | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const baseUrl = await resolveRuntimeBackendBase()
      const response = await fetch(`${baseUrl}/api/v1/agent/config/hermes/runtime`, {
        cache: "no-store",
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      setRuntime(extractRuntime(payload))
    } catch (e) {
      setRuntime(null)
      setError(e instanceof Error ? e.message : "无法读取 Hermes 运行时状态")
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const dashboardUrl = String(runtime?.dashboard_url || "").trim()
  const ready = Boolean(runtime?.dashboard_running) && dashboardUrl.length > 0

  return (
    <div className="absolute inset-0 z-20 flex flex-col bg-background">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Monitor className="h-4 w-4 text-primary" />
          <div>
            <div className="text-sm font-semibold leading-tight">官方 Hermes WebUI</div>
            <div className="text-[11px] text-muted-foreground">
              本地 hermes-webui 运行时（可选增强，非必需）
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={() => void load()} disabled={loading}>
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            重新检测
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose}>
            <X className="h-3.5 w-3.5" />
            关闭
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto">
        {loading ? (
          <div className="grid h-full place-items-center text-sm text-muted-foreground">
            <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
            正在检测 Hermes 运行时…
          </div>
        ) : ready ? (
          <iframe
            src={dashboardUrl}
            title="Hermes WebUI"
            className="block h-full w-full border-0 bg-background"
          />
        ) : (
          <div className="grid h-full place-items-center px-6">
            <div className="w-full max-w-lg space-y-3 rounded-xl border border-border/70 bg-muted/10 p-6 text-center">
              <CircleAlert className="mx-auto h-8 w-8 text-amber-500" />
              <div className="text-sm font-semibold">官方 WebUI 未运行</div>
              <p className="text-xs leading-6 text-muted-foreground">
                {error
                  ? `读取运行时状态失败：${error}`
                  : !runtime?.official_dashboard_installed
                    ? "当前安装包未包含 hermes-webui 运行时。可在「Hermes Agent → 运行设置」中安装，或直接使用左侧原生对话面板。"
                    : "hermes-webui 已安装但未启动。可在「Hermes Agent → 运行设置」启动 Dashboard。"}
              </p>
              <p className="text-[11px] leading-5 text-muted-foreground/80">
                提示：原生对话面板直连本项目后端
                <code className="mx-1 rounded bg-muted px-1 py-0.5 text-[10px]">/api/v1/agent/hermes-stream</code>
                ，不依赖外部进程，可正常使用。
              </p>
              <div className="flex justify-center gap-2 pt-1">
                <Link href="/ai-agent/settings">
                  <Button size="sm" variant="outline">
                    <ExternalLink className="mr-1.5 h-3.5 w-3.5" />
                    打开运行时设置
                  </Button>
                </Link>
                <Button size="sm" variant="ghost" onClick={onClose}>
                  返回原生对话
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
