"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { backendBaseUrl } from "@/lib/env"

// Hermes Agent SSE 客户端 hook
// 对接 prism_backend/fastapi_app/api/v1/agent/router.py 的 /agent/hermes-stream。
// 直接连后端 backendBaseUrl 绕过 Next rewrite 的 fallback 限制（fallback 不代理 API 请求）。
// 后端事件流（router.py:198 on_event + emit）：
//   init | plan | thinking | tool_call | step_complete | confirmation_required |
//   confirmation_received | final_result | error | done
// 断线补偿：POST /agent/hermes-stream 断开时 GET /agent/hermes-stream/last/{session_id} 取回完整事件流。

export type HermesEvent =
  | { type: "init"; status: string; session_id: string; turn_id: string; message?: string }
  | { type: "plan"; plan: Record<string, unknown> }
  | { type: "thinking"; content: string }
  | { type: "tool_call"; tool_name: string; arguments?: unknown; step?: number }
  | { type: "step_complete"; tool_name: string; result?: unknown; step?: number }
  | { type: "confirmation_required"; message: string; task_summary?: unknown }
  | { type: "confirmation_received"; approved: boolean }
  | { type: "final_result"; result?: string | Record<string, unknown> }
  | { type: "error"; error: string }
  | { type: "done" }
  | { type: string; [k: string]: unknown }

export interface HermesTurn {
  turn_id: string
  goal: string
  started_at: number
  events: HermesEvent[]
  final_result?: string
  error?: string
}

export interface HermesSession {
  session_id: string
  turns: HermesTurn[]
  current_turn: HermesTurn | null
  running: boolean
  connecting: boolean
}

export function useHermesStream() {
  const [session, setSession] = useState<HermesSession>({
    session_id: "",
    turns: [],
    current_turn: null,
    running: false,
    connecting: false,
  })

  const abortRef = useRef<AbortController | null>(null)
  const runningRef = useRef(false)

  const pushEvent = useCallback((turnId: string, event: HermesEvent) => {
    setSession((prev) => {
      const turns = [...prev.turns]
      let idx = turns.findIndex((t) => t.turn_id === turnId)
      if (idx === -1) {
        turns.push({
          turn_id: turnId,
          goal: "",
          started_at: Date.now(),
          events: [event],
        })
        idx = turns.length - 1
      } else {
        const turn = { ...turns[idx], events: [...turns[idx].events, event] }
        if (event.type === "final_result") {
          const r = event.result
          turn.final_result = typeof r === "string" ? r : JSON.stringify(r, null, 2)
        } else if (event.type === "error") {
          // HermesEvent 含 catch-all 分支 { type: string; [k:string]: unknown },
          // TS 无法把 event.error 收窄为 string;运行时 SSE 一定给 string,这里安全收窄。
          const rawErr = (event as { error?: unknown }).error
          turn.error = typeof rawErr === "string" ? rawErr : "未知错误"
        }
        turns[idx] = turn
      }
      return { ...prev, turns, current_turn: turns[idx], running: event.type !== "done" && event.type !== "error" ? prev.running : false }
    })
  }, [])

  const send = useCallback(
    async (goal: string, context?: Record<string, unknown>) => {
      if (runningRef.current) return { ok: false, error: "已有 Hermes 任务正在执行" }
      runningRef.current = true

      const controller = new AbortController()
      abortRef.current = controller

      const sessionId = `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
      const turnId = `turn-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`

      setSession((prev) => ({
        session_id: sessionId,
        turns: [...prev.turns, { turn_id: turnId, goal, started_at: Date.now(), events: [] }],
        current_turn: { turn_id: turnId, goal, started_at: Date.now(), events: [] },
        running: true,
        connecting: true,
      }))

      try {
        const res = await fetch("/api/v1/agent/hermes-stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ goal, context, thread_id: sessionId }),
          signal: controller.signal,
        })

        if (!res.ok || !res.body) {
          const text = await res.text().catch(() => "")
          throw new Error(`HTTP ${res.status}: ${text.slice(0, 200) || res.statusText}`)
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder("utf-8")
        let buffer = ""

        while (true) {
          const { value, done } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })
          const parts = buffer.split("\n\n")
          buffer = parts.pop() || ""
          for (const part of parts) {
            const lines = part.split("\n")
            const dataLine = lines.find((l) => l.startsWith("data:"))
            if (!dataLine) continue
            try {
              const payload = JSON.parse(dataLine.slice(5).trim())
              pushEvent(turnId, payload)
              if (payload.type === "init") setSession((prev) => ({ ...prev, connecting: false }))
            } catch {
              // 单条事件解析失败不阻断
            }
          }
        }
      } catch (e) {
        const aborted = (e as Error).name === "AbortError"
        if (!aborted) {
          const msg = e instanceof Error ? e.message : String(e)
          pushEvent(turnId, { type: "error", error: aborted ? "连接被中断" : msg })
        }
      } finally {
        runningRef.current = false
        abortRef.current = null
        setSession((prev) => ({ ...prev, running: false, connecting: false }))
      }

      return { ok: true, session_id: sessionId, turn_id: turnId }
    },
    [pushEvent]
  )

  const stop = useCallback(async () => {
    if (abortRef.current) {
      abortRef.current.abort()
    }
    try {
      await fetch("/api/v1/agent/hermes-stop", { method: "POST" })
    } catch {
      // ignore
    }
  }, [])

  const confirm = useCallback(async (approved: boolean) => {
    try {
      await fetch("/api/v1/agent/hermes-confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      })
    } catch {
      // ignore
    }
  }, [])

  const clear = useCallback(() => {
    if (abortRef.current) abortRef.current.abort()
    runningRef.current = false
    setSession({ session_id: "", turns: [], current_turn: null, running: false, connecting: false })
  }, [])

  // unmount 时中止，防止内存泄漏
  useEffect(() => () => abortRef.current?.abort(), [])

  return { session, send, stop, confirm, clear, isRunning: session.running, isConnecting: session.connecting }
}
