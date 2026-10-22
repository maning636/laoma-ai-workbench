/**
 * OpenClaw 流式执行 Hook
 * 处理 SSE 流式接收 Agent 执行状态
 */

import { useCallback, useRef, useState } from "react"
import { API_ENDPOINTS } from "@/lib/env"

export interface AgentEvent {
  type: "init" | "thinking" | "plan" | "confirmation_required" | "confirmation_received" | "tool_call" | "step_complete" | "final_result" | "error" | "done"
  status?: string
  message?: string
  content?: string
  session_id?: string
  turn_id?: string
  plan?: {
    goal?: string
    estimated_steps?: string | number
    available_tools?: Array<{ name: string; description: string }>
    strategy?: string
  }
  step?: number
  tool_name?: string
  arguments?: string | object
  result?: any
  error?: string
  approved?: boolean
}

export interface AgentStreamState {
  isStreaming: boolean
  events: AgentEvent[]
  currentThinking: string
  currentPlan: any | null
  toolCalls: Array<{
    step?: number
    toolName: string
    arguments?: string | object
    result?: any
    error?: string
    status?: "pending" | "running" | "success" | "error"
  }>
  tasks: Array<{
    id: string
    name: string
    status: "pending" | "in-progress" | "completed" | "failed"
    metadata?: Record<string, any>
  }>
  finalResult: any | null
  error: string | null
  sessionId: string | null
  turnId: string | null
}

export function useAgentStream() {
  const [state, setState] = useState<AgentStreamState>({
    isStreaming: false,
    events: [],
    currentThinking: "",
    currentPlan: null,
    toolCalls: [],
    tasks: [],
    finalResult: null,
    error: null,
    sessionId: null,
    turnId: null
  })

  const eventSourceRef = useRef<EventSource | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const resetState = useCallback(() => {
      // 终止正在进行的流，避免切换线程模式后继续往旧 UI 写入事件
    try {
      abortControllerRef.current?.abort()
    } catch {
      // ignore
    }
    abortControllerRef.current = null
    setState({
      isStreaming: false,
        events: [],
      currentThinking: "",
      currentPlan: null,
      toolCalls: [],
      tasks: [],
      finalResult: null,
      error: null,
      sessionId: null,
      turnId: null
    })
  }, [])

  /** 断线补偿：调后端 /hermes-stream/last/{session_id} 回放最近一次 turn 的完整事件流。
   *  参照 tools/easel-ref/app.py:1112 的 /api/chat/last 模式。 */
  const replayLast = useCallback(async (sessionId?: string) => {
    const sid = sessionId
    if (!sid) {
      setState(prev => ({ ...prev, error: "无 session_id，无法回放" }))
      return null
    }
    try {
      const resp = await fetch(
        `${API_ENDPOINTS.base || "http://localhost:7000"}/api/v1/agent/hermes-stream/last/${encodeURIComponent(sid)}`
      )
      if (!resp.ok) {
        setState(prev => ({ ...prev, error: `回放失败：HTTP ${resp.status}` }))
        return null
      }
      const payload = await resp.json()
      const events: AgentEvent[] = payload?.data?.events || []
      // 用当前事件处理逻辑重放
      resetState()
      setState(prev => ({ ...prev, sessionId: sid, isStreaming: false }))
      events.forEach(ev => handleEvent(ev))
      setState(prev => ({ ...prev, isStreaming: false, sessionId: sid }))
      return events
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setState(prev => ({ ...prev, error: `回放失败：${msg}` }))
      return null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetState])


  const startStreaming = useCallback(
    async (
      goal: string,
      context?: any,
      requireConfirmation: boolean = false,
      threadId?: string
    ) => {
      // 閲嶇疆鐘舵€?
      resetState()

      // 终止旧的流
      abortControllerRef.current?.abort()
      const controller = new AbortController()
      abortControllerRef.current = controller

      // 鍒涘缓 POST 璇锋眰鍙戦€佹暟鎹?
      const response = await fetch(
        `${API_ENDPOINTS.base || 'http://localhost:7000'}/api/v1/agent/hermes-stream`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          signal: controller.signal,
          body: JSON.stringify({
            goal,
            context,
            thread_id: threadId,
            require_confirmation: requireConfirmation
          })
        }
      )

      if (!response.ok) {
        const errorText = await response.text()
        const message = `HTTP ${response.status}: ${errorText}`
        setState(prev => ({
          ...prev,
          isStreaming: false,
          error: message,
          events: [...prev.events, { type: "error", error: message } as AgentEvent]
        }))
        return
      }

      // 鍒涘缓 EventSource 浠?streaming response 璇诲彇
      const reader = response.body?.getReader()
      if (!reader) {
        const message = "No response body"
        setState(prev => ({
          ...prev,
          isStreaming: false,
          error: message,
          events: [...prev.events, { type: "error", error: message } as AgentEvent]
        }))
        return
      }

      setState(prev => ({ ...prev, isStreaming: true }))

      const decoder = new TextDecoder()
      let buffer = ""

      try {
        while (true) {
          const { value, done } = await reader.read()

          if (done) break

          buffer += decoder.decode(value, { stream: true })

          // 处理可能的多个事件
          const lines = buffer.split("\n\n")
          buffer = lines.pop() || ""

          for (const line of lines) {
            if (line.startsWith("data: ")) {
              try {
                const eventData = JSON.parse(line.substring(6)) as AgentEvent
                handleEvent(eventData)
              } catch (parseError) {
                console.error("Failed to parse SSE event:", parseError, line)
              }
            }
          }
        }
      } catch (error) {
        // Abort 属于正常中断（切线程/切模式/用户停止），不当做错误展示
        if (error instanceof DOMException && error.name === "AbortError") {
          setState(prev => ({ ...prev, isStreaming: false }))
          return
        }
        console.error("Stream reading error:", error)
        const message = error instanceof Error ? error.message : String(error)
        setState(prev => ({
          ...prev,
          isStreaming: false,
          error: message,
          events: [...prev.events, { type: "error", error: message } as AgentEvent]
        }))
      }
    },
    [resetState]
  )

  const handleEvent = useCallback((event: AgentEvent) => {
    setState(prev => {
      const newEvents = [...prev.events, event]

      // 鏍规嵁浜嬩欢绫诲瀷鏇存柊鐘舵€?
      switch (event.type) {
        case "init":
          return {
            ...prev,
            events: newEvents,
            currentThinking: event.message || "",
            sessionId: event.session_id || prev.sessionId,
            turnId: event.turn_id || prev.turnId
          }

        case "thinking":
          return {
            ...prev,
            events: newEvents,
            currentThinking: event.content || ""
          }

        case "plan":
          return {
            ...prev,
            events: newEvents,
            currentPlan: event.plan
          }

        case "tool_call":
          // 添加新的工具调用
          const newToolCall = {
            step: event.step,
            toolName: event.tool_name || "unknown",
            arguments: event.arguments,
            status: "running" as const
          }

          // 鍚屾椂娣诲姞鍒颁换鍔￠槦鍒?
          const newTask = {
            id: `task-${event.step}`,
            name: event.tool_name || "unknown",
            status: "in-progress" as const,
            metadata: { args: event.arguments }
          }

          return {
            ...prev,
            events: newEvents,
            toolCalls: [...prev.toolCalls, newToolCall],
            tasks: [...prev.tasks, newTask]
          }

        case "step_complete":
          // 更新对应步骤的工具调用结果
          const updatedToolCalls = prev.toolCalls.map((call, idx) =>
            call.step === event.step
              ? { ...call, result: event.result, status: "success" as const }
              : call
          )

          const updatedTasks = prev.tasks.map((task, idx) =>
            task.id === `task-${event.step}`
              ? { ...task, status: "completed" as const, metadata: { ...task.metadata, result: event.result } }
              : task
          )

          return {
            ...prev,
            events: newEvents,
            toolCalls: updatedToolCalls,
            tasks: updatedTasks
          }

        case "final_result":
          return {
            ...prev,
            events: newEvents,
            finalResult: event.result,
            isStreaming: false
          }

        case "error":
          return {
            ...prev,
            events: newEvents,
            error: event.error || event.message || "Unknown error",
            isStreaming: false
          }

        case "done":
          return {
            ...prev,
            events: newEvents,
            isStreaming: false
          }

        default:
          return {
            ...prev,
            events: newEvents
          }
      }
    })
  }, [])

  const stopStreaming = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    try {
      abortControllerRef.current?.abort()
    } catch {
      // ignore
    }
    abortControllerRef.current = null

    // 调用后端停止 API
    fetch(`${API_ENDPOINTS.base || 'http://localhost:7000'}/api/v1/agent/hermes-stop`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    }).catch(err => console.error('Failed to stop Hermes task:', err))

    setState(prev => ({ ...prev, isStreaming: false }))
  }, [])



  return {
    ...state,
    startStreaming,
    stopStreaming,
    resetState,
    replayLast
  }
}

