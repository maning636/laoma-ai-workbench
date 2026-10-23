"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import {
  Bot,
  Brain,
  CheckCircle2,
  CircleAlert,
  Circle,
  Clock,
  Eraser,
  Loader2,
  Monitor,
  Send,
  Settings2,
  Shield,
  Square,
  Trash2,
  Wrench,
  Zap,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  useHermesStream,
  type HermesEvent,
  type HermesTurn,
} from "../useHermesStream"
import HermesSettingsDialog from "./HermesSettingsDialog"
import { HermesWebuiPanel } from "./HermesWebuiPanel"

// =============================================================
// HermesChatPage
// ------------------------------------------------------------
// 直连后端 POST /api/v1/agent/hermes-stream（SSE）。
// 后端事件：init / plan / thinking / tool_call / step_complete /
//           confirmation_required / confirmation_received /
//           final_result / error / done
// 会话数据只在前端内存里；后端也持久化了 JSONL 用于断线补偿。
// =============================================================

type MsgKind = "goal" | "thinking" | "tool_call" | "step_complete" | "final" | "error" | "confirmation" | "system"

interface RenderItem {
  kind: MsgKind
  content: string
  meta?: Record<string, unknown>
  ts: number
}

/**
 * HermesEvent 有一个 catch-all 分支 `{ type: string; [k: string]: unknown }`,
 * TS 无法把 `ev.message`/`ev.error` 等收窄成 string,因此这里统一走一个
 * "只接受 string,否则返回 fallback"的 helper,避免误把非字符串当字符串渲染。
 */
function stringOr(v: unknown, fallback: string): string {
  return typeof v === "string" && v.length > 0 ? v : fallback
}

/**
 * meta 期望是 Record<string, unknown>;SSE payload 是 JSON.parse 出来的
 * 非数组对象。这里做运行时收窄,避免把 undefined/数组当对象塞进 meta。
 */
function objectMeta(v: unknown): Record<string, unknown> | undefined {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    return v as Record<string, unknown>
  }
  return undefined
}

function eventToItem(ev: HermesEvent): RenderItem | null {
  const ts = Date.now()
  switch (ev.type) {
    case "init":
      return { kind: "system", content: stringOr(ev.message, "Hermes Agent 正在准备运行环境…"), meta: { session_id: ev.session_id, turn_id: ev.turn_id }, ts }
    case "thinking":
      return { kind: "thinking", content: stringOr(ev.content, ""), ts }
    case "tool_call": {
      const args = ev.arguments
      const argsStr = typeof args === "string" ? args : JSON.stringify(args, null, 2) || "{}"
      return { kind: "tool_call", content: argsStr, meta: { tool_name: ev.tool_name, step: ev.step }, ts }
    }
    case "step_complete": {
      const r = ev.result
      const rStr = typeof r === "string" ? r : JSON.stringify(r, null, 2) || ""
      return { kind: "step_complete", content: rStr, meta: { tool_name: ev.tool_name, step: ev.step }, ts }
    }
    case "confirmation_required":
      return { kind: "confirmation", content: stringOr(ev.message, "需要确认"), meta: objectMeta(ev.task_summary), ts }
    case "confirmation_received":
      return { kind: "system", content: ev.approved ? "用户已同意执行。" : "用户已拒绝执行。", ts }
    case "final_result": {
      const r = ev.result
      const rStr = typeof r === "string" ? r : JSON.stringify(r, null, 2) || ""
      return { kind: "final", content: rStr, ts }
    }
    case "error":
      return { kind: "error", content: stringOr(ev.error, "未知错误"), ts }
    case "done":
      return null
    default:
      return { kind: "system", content: JSON.stringify(ev, null, 2), ts }
  }
}

function TurnCard({
  turn,
  onConfirm,
}: {
  turn: HermesTurn
  onConfirm: (approved: boolean) => void
}) {
  const items = turn.events.flatMap(eventToItem).filter((x): x is RenderItem => !!x)
  const isPendingConfirm = turn.events.some((e) => e.type === "confirmation_required" && !turn.events.slice(turn.events.indexOf(e) as number).some((e2) => e2.type === "confirmation_received"))
  const running = !turn.events.some((e) => e.type === "done" || e.type === "error")

  return (
    <div id={`turn-${turn.turn_id}`} className="rounded-xl border bg-card p-4 space-y-3">
      {/* 目标 */}
      <div className="flex items-start gap-2">
        <Zap className="h-4 w-4 text-primary mt-1 shrink-0" />
        <div className="flex-1 space-y-1">
          <div className="text-xs text-muted-foreground">目标</div>
          <div className="text-sm font-medium whitespace-pre-wrap">{turn.goal}</div>
          <div className="text-[11px] text-muted-foreground">{new Date(turn.started_at).toLocaleTimeString("zh-CN")}</div>
        </div>
        {running && <Badge variant="outline" className="animate-pulse gap-1"><Loader2 className="h-3 w-3 animate-spin" />运行中</Badge>}
      </div>

      <Separator />

      {/* 事件流 */}
      {items.length === 0 ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="h-4 w-4 animate-spin" /> 正在连接 Hermes Agent…
        </div>
      ) : (
        <div className="space-y-2 max-h-[60vh] overflow-y-auto pr-1">
          {items.map((it, i) => (
            <EventRow key={i} item={it} onConfirm={onConfirm} isPendingConfirm={isPendingConfirm && it.kind === "confirmation"} />
          ))}
        </div>
      )}
    </div>
  )
}

function EventRow({
  item,
  onConfirm,
  isPendingConfirm,
}: {
  item: RenderItem
  onConfirm: (approved: boolean) => void
  isPendingConfirm: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const long = item.content.length > 200

  let icon: React.ReactNode = <Circle className="h-4 w-4 text-muted-foreground" />
  let title = "系统"
  let tone = "text-muted-foreground"
  switch (item.kind) {
    case "thinking":
      icon = <Brain className="h-4 w-4 text-amber-500" />
      title = "思考"
      tone = "text-amber-600"
      break
    case "tool_call":
      icon = <Wrench className="h-4 w-4 text-blue-500" />
      title = `调用 ${item.meta?.tool_name ?? "tool"}`
      tone = "text-blue-600"
      break
    case "step_complete":
      icon = <CheckCircle2 className="h-4 w-4 text-emerald-500" />
      title = `${item.meta?.tool_name ?? "step"} 完成`
      tone = "text-emerald-600"
      break
    case "final":
      icon = <Bot className="h-4 w-4 text-primary" />
      title = "最终结果"
      tone = "text-primary"
      break
    case "error":
      icon = <CircleAlert className="h-4 w-4 text-red-500" />
      title = "错误"
      tone = "text-red-600"
      break
    case "confirmation":
      icon = <Shield className="h-4 w-4 text-violet-500" />
      title = "需要确认"
      tone = "text-violet-600"
      break
    case "goal":
      icon = <Zap className="h-4 w-4 text-primary" />
      title = "目标"
      tone = "text-primary"
      break
    default:
      break
  }

  return (
    <div className="rounded-lg border bg-muted/30 p-2.5">
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className={`text-xs font-medium ${tone}`}>{title}</span>
        {item.meta?.step != null && <Badge variant="secondary" className="text-[10px] px-1 py-0">Step {String(item.meta.step)}</Badge>}
        <span className="ml-auto text-[10px] text-muted-foreground"><Clock className="inline h-3 w-3 mr-0.5" />{new Date(item.ts).toLocaleTimeString("zh-CN")}</span>
        {long && (
          <button type="button" onClick={() => setExpanded((v) => !v)} className="text-[11px] text-muted-foreground hover:text-foreground">
            {expanded ? "收起" : "展开"}
          </button>
        )}
      </div>
      <pre className={`whitespace-pre-wrap text-xs font-sans text-foreground/90 ${long && !expanded ? "line-clamp-3" : ""}`}>
        {item.content || "（空）"}
      </pre>
      {isPendingConfirm && (
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={() => onConfirm(true)}>同意执行</Button>
          <Button size="sm" variant="outline" onClick={() => onConfirm(false)}>拒绝</Button>
        </div>
      )}
    </div>
  )
}

export default function HermesChatPage() {
  const { session, send, stop, confirm, clear, isRunning } = useHermesStream()
  const [input, setInput] = useState("")
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [webuiOpen, setWebuiOpen] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [session.turns, session.current_turn?.events.length])

  const submit = useCallback(async () => {
    const goal = input.trim()
    if (!goal || isRunning) return
    setInput("")
    await send(goal)
  }, [input, isRunning, send])

  const historyTurns = session.turns.slice().reverse()

  return (
    <div className="relative flex h-screen">
      {/* 左：历史 turn */}
      <aside className="w-72 shrink-0 border-r bg-muted/20 flex flex-col">
        <div className="p-4 space-y-2">
          <div className="flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center">
              <Bot className="h-4 w-4 text-white" />
            </div>
            <div className="flex-1">
              <div className="text-sm font-semibold leading-tight">Hermes Agent</div>
              <div className="text-[11px] text-muted-foreground">内核运行时</div>
            </div>
          </div>
          <Separator />
          <div className="text-xs text-muted-foreground">会话历史</div>
        </div>
        <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-1">
          {historyTurns.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-foreground px-4">
              暂无历史对话。<br />在右侧输入目标，让 Hermes Agent 开始工作。
            </div>
          ) : (
            historyTurns.map((t) => (
              <button
                key={t.turn_id}
                type="button"
                onClick={() => document.getElementById(`turn-${t.turn_id}`)?.scrollIntoView({ behavior: "smooth", block: "start" })}
                className="w-full text-left rounded-lg px-3 py-2 hover:bg-muted/40 group"
              >
                <div className="text-xs font-medium truncate">{t.goal || "（未命名目标）"}</div>
                <div className="flex items-center justify-between mt-0.5">
                  <span className="text-[10px] text-muted-foreground">{new Date(t.started_at).toLocaleString("zh-CN")}</span>
                  {t.error ? <CircleAlert className="h-3 w-3 text-red-500" /> : t.final_result ? <CheckCircle2 className="h-3 w-3 text-emerald-500" /> : <Loader2 className="h-3 w-3 animate-spin text-primary" />}
                </div>
              </button>
            ))
          )}
        </div>
        <div className="p-2 space-y-1">
          {session.session_id ? (
            <div className="px-3 py-1.5 text-[10px] text-muted-foreground truncate" title={session.session_id}>
              会话：<span className="font-mono">{session.session_id}</span>
            </div>
          ) : null}
          <Button variant="ghost" size="sm" className="w-full justify-start gap-2" onClick={clear} disabled={isRunning || session.turns.length === 0}>
            <Trash2 className="h-4 w-4" /> 清空会话
          </Button>
        </div>
      </aside>

      {/* 右：主区 */}
      <main className="flex-1 flex flex-col min-w-0">
        <div className="flex items-center justify-between px-4 py-3 border-b bg-background/80 backdrop-blur">
          <div>
            <h1 className="text-base font-semibold">Hermes Agent</h1>
            <p className="text-xs text-muted-foreground">
              直连内核 <code className="px-1 py-0.5 bg-muted rounded text-[10px]">POST /api/v1/agent/hermes-stream</code>
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="gap-1.5">
              {isRunning ? <Loader2 className="h-3 w-3 animate-spin" /> : <Circle className="h-3 w-3" />}
              {isRunning ? "运行中" : "空闲"}
            </Badge>
            <Button size="sm" variant="outline" onClick={() => setWebuiOpen(true)}>
              <Monitor className="h-3.5 w-3.5" /> 官方 WebUI
            </Button>
            {isRunning && (
              <Button size="sm" variant="destructive" onClick={stop}>
                <Square className="h-4 w-4" /> 停止
              </Button>
            )}
          </div>
        </div>

        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
          {historyTurns.length === 0 ? (
            <div className="h-full grid place-items-center text-center">
              <div className="max-w-md space-y-3">
                <div className="mx-auto h-14 w-14 rounded-2xl bg-gradient-to-br from-violet-500 to-fuchsia-500 flex items-center justify-center">
                  <Bot className="h-7 w-7 text-white" />
                </div>
                <h2 className="text-lg font-semibold">向 Hermes Agent 发起一个目标</h2>
                <p className="text-sm text-muted-foreground">
                  Hermes 是老马AI研习社的内核运行时。它可以规划、调用工具、执行任务，并把结果反馈到这里。
                </p>
                <div className="grid grid-cols-1 gap-2 pt-2">
                  {[
                    "列出当前可用的技能列表",
                    "查看系统健康状态",
                    "为老马AI研习社写一篇 500 字介绍",
                  ].map((s) => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setInput(s)}
                      className="rounded-lg border bg-muted/20 px-3 py-2 text-xs text-left hover:bg-muted/40"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            historyTurns.map((t) => (
              <TurnCard key={t.turn_id} turn={t} onConfirm={confirm} />
            ))
          )}
        </div>

        <div className="border-t p-4 space-y-2">
          {isRunning && (
            <div className="flex items-center gap-2 text-xs text-amber-600">
              <Eraser className="h-3.5 w-3.5" />
              Hermes Agent 正在执行…如需停止请点右上角“停止”按钮。
            </div>
          )}
          <div className="flex gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  void submit()
                }
              }}
              placeholder="给 Hermes Agent 一个目标，Enter 发送（Shift+Enter 换行）"
              rows={3}
              disabled={isRunning}
              className="flex-1 resize-none min-h-[72px]"
            />
            <Button onClick={submit} disabled={isRunning || !input.trim()} className="self-stretch">
              {isRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
          <p className="text-[10px] text-muted-foreground flex items-center gap-1">
            <Bot className="h-3 w-3" /> 消息会由 Hermes 内核处理，可能调用工具、修改文件；敏感操作会要求你确认。
          </p>
        </div>
      </main>

      {webuiOpen && <HermesWebuiPanel onClose={() => setWebuiOpen(false)} />}
    </div>
  )
}
