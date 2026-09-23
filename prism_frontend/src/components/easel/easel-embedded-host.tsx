"use client"

import { useEffect, useMemo, useState } from "react"

import { API_ENDPOINTS } from "@/lib/env"
import { resolveRuntimeBackendBase } from "@/lib/runtime-backend"

const STARTUP_ERROR_FALLBACK = "Easel 工作台启动失败，请检查 Easel 安装与 Prism 后端日志。"

type EaselStatus = {
  running?: boolean
  pid?: number | null
  port?: number
  url?: string
  web_api_online?: boolean
  gateway_online?: boolean
  gateway_port?: number
  dir?: string
  installed?: boolean
}

function extractStatus(payload: unknown): EaselStatus | null {
  if (!payload || typeof payload !== "object") {
    return null
  }
  const result = (payload as { result?: EaselStatus }).result
  if (!result || typeof result !== "object") {
    return null
  }
  return result as EaselStatus
}

function extractErrorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === "object") {
    const responsePayload = payload as {
      message?: string
      detail?: string
      result?: { message?: string }
    }
    const candidate =
      responsePayload.result?.message || responsePayload.message || responsePayload.detail || ""
    if (String(candidate).trim()) {
      return String(candidate).trim()
    }
  }
  return `${STARTUP_ERROR_FALLBACK} (HTTP ${status})`
}

export function EaselEmbeddedHost({ active }: { active: boolean }) {
  const [backendBase, setBackendBase] = useState(API_ENDPOINTS.base)
  const [workbenchUrl, setWorkbenchUrl] = useState("")
  const [retryToken, setRetryToken] = useState(0)
  const [ready, setReady] = useState(false)
  const [booting, setBooting] = useState(false)
  const [webApiOnline, setWebApiOnline] = useState<boolean | undefined>(undefined)
  const [gatewayOnline, setGatewayOnline] = useState<boolean | undefined>(undefined)
  const [installed, setInstalled] = useState<boolean | undefined>(undefined)
  const [startupError, setStartupError] = useState("")

  useEffect(() => {
    let activeRequest = true

    const applyStatus = (status: EaselStatus | null): boolean => {
      const statusUrl = String(status?.url || "").trim()
      if (statusUrl) {
        setWorkbenchUrl(statusUrl)
      }
      setWebApiOnline(status?.web_api_online)
      setGatewayOnline(status?.gateway_online)
      setInstalled(status?.installed)
      const running = Boolean(status?.running) || Boolean(statusUrl)
      setReady(running)
      return running
    }

    const loadStatus = async (baseUrl: string): Promise<EaselStatus | null> => {
      const response = await fetch(`${baseUrl}/api/v1/easel/status`, {
        cache: "no-store",
      })
      const payload = await response.json().catch(() => ({}))
      return extractStatus(payload)
    }

    const boot = async () => {
      if (!active) return
      setBooting(true)
      setStartupError("")
      try {
        const baseUrl = await resolveRuntimeBackendBase()
        if (!activeRequest) {
          return
        }
        setBackendBase(baseUrl)

        const currentStatus = await loadStatus(baseUrl).catch(() => null)
        if (!activeRequest) {
          return
        }
        if (applyStatus(currentStatus)) {
          return
        }

        const response = await fetch(`${baseUrl}/api/v1/easel/start`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          cache: "no-store",
        })
        const payload = await response.json().catch(() => ({}))
        const status = extractStatus(payload)

        if (!response.ok) {
          throw new Error(extractErrorMessage(payload, response.status))
        }

        if (!activeRequest) {
          return
        }

        if (applyStatus(status)) {
          return
        }

        // easel web 冷启动可能较慢，后端 start 内部已轮询，这里再兜底轮询 30s
        for (let attempt = 0; attempt < 30; attempt += 1) {
          if (!activeRequest) {
            return
          }
          await new Promise((resolve) => setTimeout(resolve, 1000))
          const nextStatus = await loadStatus(baseUrl).catch(() => null)
          if (applyStatus(nextStatus)) {
            return
          }
        }
        setStartupError(STARTUP_ERROR_FALLBACK)
      } catch (error) {
        setStartupError(error instanceof Error ? error.message : STARTUP_ERROR_FALLBACK)
        try {
          const baseUrl = await resolveRuntimeBackendBase().catch(() => API_ENDPOINTS.base)
          const status = await loadStatus(baseUrl)
          applyStatus(status)
        } catch {
          // 状态面板保持可用
        }
      } finally {
        if (activeRequest) setBooting(false)
      }
    }

    void boot()
    return () => {
      activeRequest = false
    }
  }, [active, retryToken])

  useEffect(() => {
    if (active) {
      setRetryToken((current) => current + 1)
    }
  }, [active])

  const iframeSrc = useMemo(() => workbenchUrl, [workbenchUrl])

  return (
    <div
      className={
        active
          ? "absolute inset-0 z-10 bg-card"
          : "pointer-events-none absolute inset-0 -z-10 bg-card opacity-0"
      }
      data-backend-base={backendBase}
    >
      {ready ? (
        <iframe
          src={iframeSrc}
          title="Easel Workbench"
          className="block h-full w-full border-0 bg-card"
        />
      ) : (
        <div className="grid h-full place-items-center bg-card px-6 text-foreground">
          <div className="w-full max-w-lg rounded-2xl border border-border/70 bg-foreground/5 p-8 text-center shadow-2xl">
            <div className="text-lg font-semibold">
              {booting ? "正在启动 Easel 工作台…" : "Easel 工作台暂不可用"}
            </div>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              {startupError || "正在读取 Easel 运行时状态。"}
            </p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-2 text-xs text-muted-foreground">
              <span className="rounded-full border border-border/70 px-2.5 py-1">
                Easel Web:{" "}
                {webApiOnline === undefined ? "检测中…" : webApiOnline ? "在线" : "离线"}
              </span>
              <span className="rounded-full border border-border/70 px-2.5 py-1">
                OpenClaw Gateway:{" "}
                {gatewayOnline === undefined ? "检测中…" : gatewayOnline ? "在线" : "离线"}
              </span>
              {installed === false && (
                <span className="rounded-full border border-red-500/50 px-2.5 py-1 text-red-500">
                  未安装
                </span>
              )}
            </div>
            <div className="mt-6 flex justify-center gap-3">
              <button
                type="button"
                onClick={() => setRetryToken((current) => current + 1)}
                disabled={booting}
                className="rounded-xl border border-border/70 px-4 py-2 text-sm disabled:opacity-50"
              >
                重试启动
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
