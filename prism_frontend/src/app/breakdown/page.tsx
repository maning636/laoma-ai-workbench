"use client"

import { useCallback, useEffect, useMemo, useRef, useState, type ElementType } from "react"
import {
  AlertTriangle,
  BookOpenText,
  Files,
  GitFork,
  History,
  Loader2,
  RefreshCw,
  Send,
  Sparkles,
  TriangleAlert,
  Workflow,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/use-toast"

interface BreakdownBlock {
  index: number
  title: string
  detail?: string
}

interface Breakdown {
  content: string
  summary?: string
  structure?: string
  hooks?: string[]
  beats?: BreakdownBlock[]
  insights?: string[]
  actionItems?: string[]
  risks?: string[]
}

const HISTORY_KEY = "lao_ma.breakdown.history"
const HISTORY_LIMIT = 12

const SYSTEM_PROMPT = [
  "你是资深内容策划，擅长把一条选题/文案拆解成可执行的结构化要点。",
  "只输出 JSON，不要任何解释、前后缀或 markdown 代码块标记。",
  "JSON 结构严格为：",
  '{"summary":"一句话概括","structure":"内容骨架（如 3-2-1 / 总-分-总）","hooks":["开头钩子1","开头钩子2"],"beats":[{"title":"段落/环节标题","detail":"要点说明"}],"insights":["可复用的观察1","可复用的观察2"],"actionItems":["下一步动作1"],"risks":["注意点/风险1"]}',
  "如果输入信息不足，用最保守的判断并在 risks 里说明信息缺失，不要编造事实、数据或来源。",
].join("\n")

const HEURISTIC_NOTES = [
  "输入过短，AI 拆解效果有限，建议补充完整文案或背景。",
  "标题与正文信息重合，可考虑压缩成单一钩子。",
  "未识别到明确的开头钩子，建议补一句悬念或反差。",
  "未识别到明确的行动号召，建议结尾加一句引导。",
]

function parseDetail(detail: unknown): string {
  if (typeof detail === "string") return detail
  try {
    return JSON.stringify(detail)
  } catch {
    return "未知错误"
  }
}

function stripFences(text: string): string {
  const s = text.trim()
  if (!s) return s
  if (s.startsWith("```")) {
    const nl = s.indexOf("\n")
    const last = s.lastIndexOf("```")
    if (nl > -1 && last > nl) return s.slice(nl + 1, last).trim()
  }
  const a = s.indexOf("{")
  const b = s.lastIndexOf("}")
  if (a > -1 && b > a) return s.slice(a, b + 1)
  return s
}

function asStrings(v: unknown): string[] {
  if (!Array.isArray(v)) return []
  return v.map((x) => String(x || "").trim()).filter(Boolean)
}

function normalizeBreakdown(raw: unknown): Breakdown {
  const o = (raw && typeof raw === "object" ? raw : {}) as Record<string, unknown>
  const beats: BreakdownBlock[] = Array.isArray(o.beats)
    ? o.beats.map((b, i) => {
        const x = (b && typeof b === "object" ? b : {}) as Record<string, unknown>
        return { index: i + 1, title: String(x.title || x.name || `要点 ${i + 1}`).trim() || `要点 ${i + 1}`, detail: String(x.detail || x.desc || "").trim() }
      })
    : []
  return {
    content: String(o.content || "").trim(),
    summary: String(o.summary || "").trim(),
    structure: String(o.structure || "").trim(),
    hooks: asStrings(o.hooks),
    beats,
    insights: asStrings(o.insights),
    actionItems: asStrings(o.actionItems),
    risks: asStrings(o.risks),
  }
}

function heuristicBreakdown(text: string): Breakdown {
  const lines = text.split(/\n+/).map((l) => l.trim()).filter(Boolean)
  const title = lines[0] || ""
  const beats: BreakdownBlock[] = lines.slice(0, 6).map((l, i) => ({
    index: i + 1,
    title: l.length > 24 ? `${l.slice(0, 24)}…` : l,
    detail: l.length > 24 ? l : "",
  }))
  return {
    content: text,
    summary: title ? `${title}（结构化拆解示意）` : "结构化拆解示意",
    structure: `共 ${lines.length} 段`,
    hooks: title ? [title] : [],
    beats,
    insights: lines.length > 1 ? ["分段拆解为本地启发式结果，段落级要点可直接编辑复用。"] : [],
    actionItems: ["补充完整文案后重新拆解，可获得钩子/骨架/风险等 AI 维度。"],
    risks: ["该结果由本地规则生成，不含 AI 判断；建议接入 AI 后复核。"],
  }
}

function heuristicRisks(text: string): string[] {
  if (!text.trim()) return ["输入为空，无法拆解。"]
  if (text.trim().length < 24) return HEURISTIC_NOTES.slice(0, 2)
  const out: string[] = []
  if (!/[？?！!]/.test(text.slice(0, 40))) out.push(HEURISTIC_NOTES[2])
  if (text.trim().length < 80) out.push(HEURISTIC_NOTES[0])
  if (!/(关注|点赞|收藏|转发|评论|订阅|下单|点击)/.test(text)) out.push(HEURISTIC_NOTES[3])
  return out.length ? out : ["未识别到明显风险，但内容较短，建议补充更多上下文。"]
}

function loadHistory(): Breakdown[] {
  try {
    const raw = window.localStorage.getItem(HISTORY_KEY)
    const arr = raw ? JSON.parse(raw) : []
    return Array.isArray(arr) ? arr.filter((x) => x && typeof x === "object") : []
  } catch {
    return []
  }
}

function saveHistory(list: Breakdown[]) {
  try {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, HISTORY_LIMIT)))
  } catch {
    /* localStorage 不可用时静默忽略 */
  }
}

const SECTIONS: { key: keyof Breakdown; label: string; icon: ElementType }[] = [
  { key: "summary", label: "一句话概括", icon: Sparkles },
  { key: "structure", label: "内容骨架", icon: Workflow },
  { key: "hooks", label: "开头钩子", icon: GitFork },
  { key: "beats", label: "分段拆解", icon: Files },
  { key: "insights", label: "可复用观察", icon: BookOpenText },
  { key: "actionItems", label: "下一步动作", icon: Send },
  { key: "risks", label: "注意点 / 风险", icon: AlertTriangle },
]

export default function BreakdownPage() {
  const { toast } = useToast()
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [aiOnline, setAiOnline] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<Breakdown | null>(null)
  const [history, setHistory] = useState<Breakdown[]>([])
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    setHistory(loadHistory())
  }, [])

  useEffect(() => () => abortRef.current?.abort(), [])

  const run = useCallback(
    async (text: string) => {
      const t = text.trim()
      if (!t) {
        toast({ variant: "destructive", title: "请输入要拆解的选题或文案" })
        return
      }
      setBusy(true)
      setError(null)
      const ac = new AbortController()
      abortRef.current = ac
      try {
        const res = await fetch("/api/v1/fusion/breakdown", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ topic: t }),
          signal: ac.signal,
        })
        const data = await res.json().catch(() => ({}))
        if (!res.ok || data?.status !== "success" || !data?.result) {
          throw new Error(parseDetail(data?.detail || data?.error || `接口返回 ${res.status}`))
        }
        const bd = normalizeBreakdown({ ...data.result, content: t })
        bd.content = t
        setAiOnline(true)
        setResult(bd)
        setHistory((prev) => {
          const next = [bd, ...prev.filter((x) => x.content !== t)].slice(0, HISTORY_LIMIT)
          saveHistory(next)
          return next
        })
        const meta = (data.result as any)?._meta
        toast({
          title: "拆解完成",
          description: meta?.model ? `模型：${meta.model} · 用时 ${meta.elapsed_seconds}s` : undefined,
        })
      } catch (e) {
        if (ac.signal.aborted) return
        setAiOnline(false)
        const msg = e instanceof Error ? e.message : String(e)
        setError(msg)
        const fallback = heuristicBreakdown(t)
        fallback.risks = [...heuristicRisks(t), ...fallback.risks].slice(0, 5)
        setResult(fallback)
        toast({ variant: "destructive", title: "AI 拆解失败，已用本地规则给出示意拆解", description: msg })
      } finally {
        setBusy(false)
        abortRef.current = null
      }
    },
    [toast],
  )

  const pickFromIdeas = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/content-library/ideas", { cache: "no-store" })
      const data = await res.json()
      const ideas = Array.isArray(data?.result?.ideas) ? data.result.ideas : []
      if (ideas.length === 0) {
        toast({ variant: "destructive", title: "选题库为空", description: "可先去「选题库」登记选题" })
        return
      }
      const first = ideas[0]
      const text = String(first?.title || "").trim()
      if (!text) {
        toast({ variant: "destructive", title: "首个选题缺少标题" })
        return
      }
      setInput(text)
      void run(text)
    } catch (e) {
      toast({ variant: "destructive", title: "读取选题库失败", description: e instanceof Error ? e.message : String(e) })
    }
  }, [run, toast])

  const stats = useMemo(() => {
    const t = input.trim()
    const chars = t.length
    return {
      chars,
      lines: t ? t.split("\n").length : 0,
    }
  }, [input])

  const renderValue = (v: unknown) => {
    if (typeof v === "string" && v) return <p className="text-sm leading-relaxed">{v}</p>
    if (Array.isArray(v) && v.length) return null
    return <p className="text-xs text-muted-foreground">—</p>
  }

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · BREAKDOWN"
        title="内容拆解"
        description="把一条选题或文案拆成钩子、骨架、分段要点、可复用观察与风险点。"
        actions={
          <>
            <Button variant="outline" onClick={pickFromIdeas} disabled={busy}>
              <Files className="h-4 w-4" /> 从选题库取一条
            </Button>
            <Button onClick={() => void run(input)} disabled={busy || !input.trim()}>
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              {busy ? "拆解中" : "开始拆解"}
            </Button>
          </>
        }
      />

      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        <Card className="p-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium">
                <BookOpenText className="h-4 w-4 text-primary" /> 输入选题 / 文案
              </div>
              <span className="font-mono text-xs text-muted-foreground">{stats.chars} 字 · {stats.lines} 行</span>
            </div>
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              rows={6}
              placeholder={"粘贴标题、口播稿、笔记正文或选题描述…\n例如：宝妈必看｜0 元试用的 3 个隐藏入口，最后一条 90% 的人不知道"}
              className="min-h-[8rem]"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-1.5">
                {aiOnline === null ? (
                  <Badge variant="outline" className="text-xs">AI 状态未知</Badge>
                ) : aiOnline ? (
                  <Badge variant="accent" className="text-xs">AI 可用 · SenseNova glm-5.2</Badge>
                ) : (
                  <Badge variant="destructive" className="text-xs">AI 不可用 · 本地示意</Badge>
                )}
                <span className="text-xs text-muted-foreground">数据源：POST /api/v1/fusion/breakdown（商汤直连）</span>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setInput("")} disabled={busy || !input}>
                清空
              </Button>
            </div>
          </div>
        </Card>

        {error && (
          <Card className="border-destructive/40 p-4">
            <div className="flex items-start gap-2 text-sm">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              <div className="min-w-0">
                <p className="font-medium text-destructive">拆解请求失败</p>
                <p className="mt-0.5 break-words text-xs text-foreground/70">{error}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  下方为本地规则兜底结果；接口 <code className="font-mono">POST /api/v1/fusion/breakdown</code> 恢复后可重新拆解获取 AI 维度。
                </p>
              </div>
            </div>
          </Card>
        )}

        {busy && (
          <Card className="p-10 text-center text-muted-foreground">
            <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在拆解，请稍候…
          </Card>
        )}

        {result && !busy && (
          <div className="grid gap-4 md:grid-cols-2">
            {SECTIONS.map((s) => {
              const Icon = s.icon
              const val = result[s.key]
              const isText = s.key === "summary" || s.key === "structure"
              const isList = Array.isArray(val)
              const empty = isText ? !val : !isList || val.length === 0
              return (
                <Card key={s.key} className="p-4">
                  <div className="mb-2 flex items-center gap-2">
                    <Icon className="h-4 w-4 text-primary" />
                    <span className="text-sm font-medium">{s.label}</span>
                    {isList && !empty && <Badge variant="outline" className="text-xs">{val.length}</Badge>}
                  </div>
                  {isList && !empty ? (
                    <ul className="space-y-1.5">
                      {(val as unknown[]).map((x, i) => {
                        const beat = (x && typeof x === "object") ? (x as { index?: number; title?: string; detail?: string }) : null
                        return (
                          <li key={i} className="flex items-start gap-2 text-sm">
                            <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                            {beat ? (
                              <span className="flex-1">
                                {beat.index ? <span className="text-muted-foreground">{beat.index}. </span> : null}
                                <span className="font-medium">{beat.title}</span>
                                {beat.detail ? <span className="text-muted-foreground"> — {beat.detail}</span> : null}
                              </span>
                            ) : (
                              <span>{String(x)}</span>
                            )}
                          </li>
                        )
                      })}
                    </ul>
                  ) : (
                    renderValue(isText ? val : undefined)
                  )}
                </Card>
              )
            })}
          </div>
        )}

        <Card className="p-4">
          <div className="mb-2 flex items-center justify-between">
            <span className="flex items-center gap-2 text-sm font-medium">
              <History className="h-4 w-4 text-primary" /> 拆解历史
            </span>
            {history.length > 0 && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setHistory([])
                  saveHistory([])
                }}
              >
                清空
              </Button>
            )}
          </div>
          {history.length === 0 ? (
            <p className="py-4 text-center text-xs text-muted-foreground">暂无历史。拆解结果会保留在本地浏览器中。</p>
          ) : (
            <div className="space-y-1.5">
              {history.map((h, i) => {
                const head = h.summary || h.content || "未命名拆解"
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      setInput(h.content)
                      setResult(h)
                      setError(null)
                      window.scrollTo({ top: 0, behavior: "smooth" })
                    }}
                    className="flex w-full items-center gap-2 rounded-lg border p-2.5 text-left transition hover:border-primary/40"
                  >
                    <Files className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate text-sm">{head}</span>
                    {h.beats?.length ? <Badge variant="outline" className="text-xs">{h.beats.length} 段</Badge> : null}
                  </button>
                )
              })}
            </div>
          )}
        </Card>

        <p className="text-xs text-muted-foreground">
          说明：拆解走 <code className="font-mono">POST /api/v1/fusion/breakdown</code>（商汤 SenseNova 直连，glm-5.2），接口异常时回退本地规则示意拆解。
        </p>
      </div>
    </div>
  )
}
