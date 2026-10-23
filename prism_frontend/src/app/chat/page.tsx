"use client"

import { useCallback, useEffect, useState, type MouseEvent } from "react"
import { Loader2, Plus, Send, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { chatViaCloud } from "@/lib/cloud-chat"
import {
  describeCloudLlmAvailability,
  probeCloudLlmAvailability,
  type CloudLlmAvailability,
} from "@/lib/cloud-llm-availability"

interface Thread {
  id: string
  title: string
  updated_at?: string
}

interface ChatMsg {
  role: "user" | "assistant"
  content: string
}

export default function ChatPage() {
  const [threads, setThreads] = useState<Thread[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState("")
  const [sending, setSending] = useState(false)
  const [loadingThreads, setLoadingThreads] = useState(true)
  const [configError, setConfigError] = useState("")
  const [lastSource, setLastSource] = useState<string | null>(null)
  // P7:云端 LLM 可用性。只有明确"未配置"(unavailable)才跳过云端;
  // 探测失败(unknown)一律保持原有行为,不能因网络抖动误伤正常用户。
  const [cloudAvailability, setCloudAvailability] =
    useState<CloudLlmAvailability>("unknown")
  const [cloudAvailabilityMessage, setCloudAvailabilityMessage] = useState("")

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const r = await probeCloudLlmAvailability()
      if (cancelled) return
      setCloudAvailability(r.availability)
      setCloudAvailabilityMessage(describeCloudLlmAvailability(r.availability, r.message))
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const loadThreads = useCallback(async () => {
    setLoadingThreads(true)
    try {
      const res = await fetch("/api/v1/ai/threads", { cache: "no-store" })
      const data = await res.json()
      setThreads(data?.data?.threads || data?.result?.threads || [])
    } finally {
      setLoadingThreads(false)
    }
  }, [])

  useEffect(() => {
    void loadThreads()
  }, [loadThreads])

  const loadMessages = useCallback(async (threadId: string) => {
    const res = await fetch(`/api/v1/ai/threads/${threadId}/messages`, { cache: "no-store" })
    const data = await res.json()
    const list: ChatMsg[] = ((data?.data?.messages || data?.result?.messages || []) as Array<Record<string, unknown>>)
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role as ChatMsg["role"], content: String(m.content || "") }))
    setMessages(list)
  }, [])

  const pickThread = (t: Thread) => {
    setActiveId(t.id)
    setMessages([])
    void loadMessages(t.id)
  }

  const newThread = async (): Promise<string> => {
    const res = await fetch("/api/v1/ai/threads/", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "新对话" }),
    })
    const data = await res.json()
    const id = data?.data?.thread_id || data?.thread_id || data?.result?.thread_id
    if (!id) throw new Error("创建会话失败")
    await loadThreads()
    setActiveId(id)
    setMessages([])
    return id
  }

  const deleteThread = async (id: string, e: MouseEvent) => {    e.stopPropagation()
    await fetch(`/api/v1/ai/threads/${id}`, { method: "DELETE" })
    if (activeId === id) {
      setActiveId(null)
      setMessages([])
    }
    await loadThreads()
  }

  const send = async () => {
    const text = input.trim()
    if (!text || sending) return
    setInput("")
    setSending(true)
    setConfigError("")

    let threadId = activeId
    try {
      if (!threadId) threadId = await newThread()
      const history = [...messages, { role: "user" as const, content: text }]
      setMessages(history)

      // F-A: 优先走云端流式(gatewayStream);失败自动回落到云端非流式 /cloud/llm/chat,
      // 再失败回落到本地非流式 /api/v1/ai/chat。三层任一成功即返回。
      // onDelta 逐字更新 UI(云端流式路径)。
      const placeholderIdx = history.length
      setMessages((prev) => [...prev, { role: "assistant", content: "" }])

      const res = await chatViaCloud({
        messages: history,
        // 云端明确未配置 → 跳过云端两层,直接本地。
        skipCloud: cloudAvailability === "unavailable",
        onDelta: (delta) => {
          setMessages((prev) => {
            if (prev.length <= placeholderIdx) return prev
            const next = [...prev]
            next[placeholderIdx] = {
              role: "assistant",
              content: (next[placeholderIdx]?.content || "") + delta,
            }
            return next
          })
        },
      })

      // chatViaCloud 全部失败:清掉占位气泡,展示错误
      if (!res.ok) {
        setMessages((prev) => {
          const next = [...prev]
          if (next.length > placeholderIdx && !next[placeholderIdx]?.content) {
            next.pop()
          }
          next.push({ role: "assistant", content: `⚠️ ${res.detail || "AI 服务暂时不可用"}` })
          return next
        })
        setConfigError(res.detail || `HTTP error: ${res.code}`)
        return
      }

      // 成功:替换占位气泡(云端流式已实时更新;云端 chat / 本地 chat 需要一次性填入)
      const reply = res.text || "（空回复）"
      setMessages((prev) => {
        const next = [...prev]
        next[placeholderIdx] = { role: "assistant", content: reply }
        return next
      })
      await fetch(`/api/v1/ai/threads/${threadId}/messages/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: [
            { role: "user", content: text },
            { role: "assistant", content: reply },
          ],
        }),
      })
      setLastSource(res.source)
      await loadThreads()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setConfigError(msg)
      setMessages((prev) => [...prev, { role: "assistant", content: `⚠️ ${msg}` }])
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex h-screen">
      {/* 会话列表 */}
      <div className="flex w-64 shrink-0 flex-col border-r bg-muted/20">
        <div className="p-3">
          <Button variant="outline" className="w-full" onClick={newThread}>
            <Plus className="h-4 w-4 mr-1.5" /> 新会话
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-2">
          {loadingThreads ? (
            <div className="py-6 text-center text-xs text-muted-foreground">
              <Loader2 className="mx-auto h-4 w-4 animate-spin" />
            </div>
          ) : threads.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-foreground">暂无会话</div>
          ) : (
            threads.map((t) => (
              <div
                key={t.id}
                onClick={() => pickThread(t)}
                className={cn(
                  "group mb-1 flex cursor-pointer items-center justify-between rounded-lg px-3 py-2 text-sm transition",
                  activeId === t.id ? "bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted/40",
                )}
              >
                <span className="truncate">{t.title}</span>
                <Trash2
                  className="h-3.5 w-3.5 shrink-0 opacity-0 transition group-hover:opacity-60 hover:!opacity-100"
                  onClick={(e) => deleteThread(t.id, e)}
                />
              </div>
            ))
          )}
        </div>
      </div>

      {/* 对话主区 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex-1 space-y-4 overflow-y-auto p-6">
          {messages.length === 0 ? (
            <div className="grid h-full place-items-center text-center text-sm text-muted-foreground">
              <div>
                <p>开始你的第一段对话。</p>
                <p className="mt-2 text-xs">
                  对话由老马AI研习社内置 AI 服务驱动（Settings → AI 服务商配置 → chat 类型）。
                </p>
              </div>
            </div>
          ) : (
            messages.map((m, i) => (
              <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div
                  className={cn(
                    "max-w-[75%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed",
                    m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted",
                  )}
                >
                  {m.content}
                </div>
              </div>
            ))
          )}
          {sending && (
            <div className="flex justify-start">
              <div className="rounded-2xl bg-muted px-4 py-2.5">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            </div>
          )}
          {lastSource && !sending && (
            <div className="text-right text-[10px] text-muted-foreground">
              {lastSource === "cloud-stream" && "云端流式 · 逐字"}
              {lastSource === "cloud-chat" && "云端非流式"}
              {lastSource === "local-chat" &&
                (cloudAvailability === "unavailable"
                  ? "本地对话 · 云端 AI 未配置"
                  : "本地对话")}
            </div>
          )}
          {cloudAvailability === "unavailable" && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-600">
              {cloudAvailabilityMessage}
            </div>
          )}
        </div>

        <div className="border-t p-4">
          {configError && (
            <div className="mb-2 rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-600">
              {configError} —— 请到 Settings → AI 服务商配置 添加 chat 类型模型后重试。
            </div>
          )}
          <div className="flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  void send()
                }
              }}
              placeholder="输入消息，Enter 发送（Shift+Enter 换行）…"
              disabled={sending}
            />
            <Button onClick={send} disabled={sending || !input.trim()}>
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
      {/* 消息区 overflow-y-auto 自带滚动 */}
    </div>
  )
}
