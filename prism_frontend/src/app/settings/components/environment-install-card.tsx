"use client"

import { useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { useToast } from "@/components/ui/use-toast"
import { API_ENDPOINTS } from "@/lib/env"
import {
  Check,
  CircleAlert,
  CircleDashed,
  Cpu,
  Loader2,
  RefreshCw,
} from "lucide-react"

type CheckState = "unknown" | "checking" | "installed" | "missing"

type EngineKey = "hermes" | "whisper" | "hyperframes"

type EngineRow = {
  key: EngineKey
  name: string
  description: string
  status: CheckState
  detail: string
  installHint: string
}

type HealthCheckPayload = {
  status?: string
  components?: Record<string, string>
  timestamp?: string
  detail?: string
}

type BrowserRuntimePayload = {
  browserRuntimeInfo?: {
    pythonPath?: string
    activeRuntime?: string | null
    runtimes?: Record<string, { installed?: boolean; version?: string | null }>
  }
  success?: boolean
  detail?: string
}

type SharedScriptsPayload = {
  status?: string
  result?:
    | Array<{ name?: string; script?: string }>
    | { items?: Array<{ name?: string; script?: string }> }
    | null
  detail?: string
}

function StatusBadge({ state }: { state: CheckState }) {
  if (state === "installed") {
    return (
      <Badge variant="outline" className="border-border/80 bg-popover text-foreground">
        <Check className="mr-1 h-3 w-3" />
        已安装
      </Badge>
    )
  }
  if (state === "missing") {
    return (
      <Badge variant="outline" className="border-border/70 bg-card text-foreground/70">
        <CircleAlert className="mr-1 h-3 w-3" />
        未安装
      </Badge>
    )
  }
  if (state === "checking") {
    return (
      <Badge variant="outline" className="border-border/70 bg-card text-muted-foreground">
        <Loader2 className="mr-1 h-3 w-3 animate-spin" />
        检查中
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="border-border/70 bg-card text-muted-foreground">
      <CircleDashed className="mr-1 h-3 w-3" />
      未知
    </Badge>
  )
}

const INITIAL_ROWS: EngineRow[] = [
  {
    key: "hermes",
    name: "Hermes Agent",
    description: "本地 Hermes Gateway / Dashboard 进程与运行时",
    status: "unknown",
    detail: "等待体检",
    installHint: "请通过 supervisor 启动 Hermes 服务（supervisor/restart）后重新体检",
  },
  {
    key: "whisper",
    name: "本地 Whisper",
    description: "Easel faster-whisper（asr.py）与本地模型文件",
    status: "unknown",
    detail: "等待体检",
    installHint: "运行 .venv 中的 install 脚本下载 faster-whisper 及模型",
  },
  {
    key: "hyperframes",
    name: "HyperFrames",
    description: "视频帧渲染引擎（Easel 侧）",
    status: "unknown",
    detail: "等待体检",
    installHint: "HyperFrames 引擎随 Easel 更新接入，安装接口待接入",
  },
]

export function EnvironmentInstallCard() {
  const { toast } = useToast()
  const [rows, setRows] = useState<EngineRow[]>(INITIAL_ROWS)
  const [refreshing, setRefreshing] = useState(false)

  const setRow = useCallback((key: EngineKey, patch: Partial<EngineRow>) => {
    setRows((prev) => prev.map((row) => (row.key === key ? { ...row, ...patch } : row)))
  }, [])

  const refreshAll = useCallback(async () => {
    setRefreshing(true)
    setRows((prev) => prev.map((row) => ({ ...row, status: "checking", detail: "检查中..." })))

    // 1) Hermes：走 /api/v1/system/health-check 的 ai_service 与 database 状态
    try {
      const res = await fetch(`${API_ENDPOINTS.base}/api/v1/system/health-check`, {
        cache: "no-store",
      })
      const payload = (await res.json().catch(() => ({}))) as HealthCheckPayload
      if (!res.ok) throw new Error(payload?.detail || "健康检查失败")
      const aiState = payload.components?.ai_service ?? "not_available"
      const dbState = payload.components?.database ?? "unknown"
      if (aiState === "healthy" || aiState === "not_available") {
        setRow("hermes", {
          status: "installed",
          detail: `AI 服务：${aiState}；数据库：${dbState}`,
        })
      } else {
        setRow("hermes", {
          status: "missing",
          detail: `AI 服务状态异常：${aiState}`,
        })
      }
    } catch (error) {
      setRow("hermes", {
        status: "missing",
        detail: error instanceof Error ? error.message : "健康检查失败",
      })
    }

    // 2) Whisper：/api/v1/system/browser-runtime/status 里的 pythonPath 作为 venv 存在信号
    try {
      const res = await fetch(`${API_ENDPOINTS.base}/api/v1/system/browser-runtime/status`, {
        cache: "no-store",
      })
      const payload = (await res.json().catch(() => ({}))) as BrowserRuntimePayload
      if (!res.ok) throw new Error(payload?.detail || "运行时状态查询失败")
      const pythonPath = payload.browserRuntimeInfo?.pythonPath ?? ""
      if (pythonPath) {
        setRow("whisper", {
          status: "installed",
          detail: `venv 就绪：${pythonPath}（模型文件请见 .venv 目录）`,
        })
      } else {
        setRow("whisper", {
          status: "missing",
          detail: "未检测到 .venv Python 环境",
        })
      }
    } catch (error) {
      setRow("whisper", {
        status: "missing",
        detail: error instanceof Error ? error.message : "运行时状态查询失败",
      })
    }

    // 3) HyperFrames：/api/v1/skills/shared-scripts 里搜 hyperframes 关键词
    try {
      const res = await fetch(`${API_ENDPOINTS.base}/api/v1/skills/shared-scripts`, {
        cache: "no-store",
      })
      const payload = (await res.json().catch(() => ({}))) as SharedScriptsPayload
      if (!res.ok) throw new Error(payload?.detail || "skills 查询失败")
      const items = Array.isArray(payload.result)
        ? payload.result
        : (payload.result?.items ?? [])
      const hit = items.find((item) => {
        const text = `${item.name ?? ""} ${item.script ?? ""}`.toLowerCase()
        return text.includes("hyperframes") || text.includes("hyper_frames")
      })
      if (hit) {
        setRow("hyperframes", {
          status: "installed",
          detail: `已注册：${String(hit.script ?? hit.name)}`,
        })
      } else {
        setRow("hyperframes", {
          status: "missing",
          detail: `Easel skills 目录已加载 ${items.length} 个脚本，未发现 HyperFrames 入口`,
        })
      }
    } catch (error) {
      setRow("hyperframes", {
        status: "missing",
        detail: error instanceof Error ? error.message : "skills 查询失败",
      })
    }

    setRefreshing(false)
    toast({
      title: "体检完成",
      description: "已刷新 Hermes / Whisper / HyperFrames 状态",
    })
  }, [setRow, toast])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  return (
    <Card className="border-border/70 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-foreground">
          <Cpu className="h-5 w-5 text-foreground/70" />
          本地引擎体检
        </CardTitle>
        <CardDescription className="text-muted-foreground">
          一键检查 Hermes Agent / 本地 Whisper / HyperFrames 是否就绪，缺失时按需安装。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap gap-3">
          <Button
            variant="secondary"
            onClick={() => void refreshAll()}
            disabled={refreshing}
            className="border-border/70 bg-card text-foreground hover:bg-accent/40"
          >
            {refreshing ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-2 h-4 w-4" />
            )}
            重新体检
          </Button>
        </div>

        <div className="space-y-3">
          {rows.map((row) => (
            <div key={row.key} className="rounded-xl border border-border/70 bg-card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="font-medium text-foreground">{row.name}</div>
                    <StatusBadge state={row.status} />
                    <span className="font-mono text-[11px] text-muted-foreground">{row.key}</span>
                  </div>
                  <div className="text-xs text-muted-foreground">{row.description}</div>
                  <div className="text-xs leading-5 text-foreground/70">{row.detail}</div>
                  {row.status === "missing" ? (
                    <div className="mt-2 rounded-lg border border-dashed border-border/70 bg-card/40 px-3 py-2 text-[11px] leading-4 text-muted-foreground">
                      安装提示：{row.installHint}
                    </div>
                  ) : null}
                </div>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={row.status === "installed" || refreshing}
                  onClick={() =>
                    toast({
                      title: "安装接口待接入",
                      description: row.installHint,
                    })
                  }
                  className="border-border/70 bg-card text-foreground/70 hover:bg-accent/40"
                >
                  {row.status === "installed" ? "已就绪" : "安装(待接入)"}
                </Button>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
