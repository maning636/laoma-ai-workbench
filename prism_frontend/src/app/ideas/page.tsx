"use client"

import { useCallback, useEffect, useState } from "react"
import {
  CheckCircle2,
  Clock,
  Flame,
  Loader2,
  NotebookPen,
  Pencil,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  TriangleAlert,
  Trash2,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/use-toast"

interface Idea {
  id: string
  title: string
  note?: string
  source?: string
  status?: string
  created?: number
}

interface PerfSuggestion {
  id?: string
  title: string
  note?: string
  heat: number
  platform?: string
}

type PerfState =
  | { kind: "hint"; hint: string }
  | { kind: "suggestions"; suggestions: PerfSuggestion[] }

function clampHeat(h: number | undefined | null): number {
  if (typeof h !== "number" || Number.isNaN(h)) return 0
  return Math.max(0, Math.min(1, h))
}

const STATUSES = [
  { key: "pending", label: "待启动", icon: Clock },
  { key: "doing", label: "进行中", icon: Pencil },
  { key: "done", label: "已完成", icon: CheckCircle2 },
] as const

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "pending", label: "待启动" },
  { key: "doing", label: "进行中" },
  { key: "done", label: "已完成" },
] as const

type FilterKey = (typeof FILTERS)[number]["key"]

function statusMeta(status?: string) {
  return STATUSES.find((s) => s.key === status) || STATUSES[0]
}

function fmtCreated(ts?: number): string {
  if (!ts) return "—"
  const d = new Date(ts * 1000)
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString("zh-CN", { hour12: false })
}

function newId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID()
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function parseDetail(detail: unknown): string {
  if (typeof detail === "string") return detail
  try {
    return JSON.stringify(detail)
  } catch {
    return "未知错误"
  }
}

export default function IdeasPage() {
  const { toast } = useToast()
  const [ideas, setIdeas] = useState<Idea[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterKey>("all")

  const [showForm, setShowForm] = useState(false)
  const [title, setTitle] = useState("")
  const [note, setNote] = useState("")
  const [source, setSource] = useState("")

  const [perfLoading, setPerfLoading] = useState(false)
  const [perf, setPerf] = useState<PerfState | null>(null)

  const loadPerformance = useCallback(async () => {
    setPerfLoading(true)
    setPerf(null)
    try {
      const res = await fetch("/api/v1/content-library/ideas/from-performance", { cache: "no-store" })
      if (!res.ok) throw new Error(`接口返回 ${res.status}`)
      const data = await res.json()
      const result = data?.result ?? {}
      const raw = Array.isArray(result?.suggestions) ? (result.suggestions as PerfSuggestion[]) : []
      const hint = typeof result?.hint === "string" ? result.hint : ""
      if (result?.data_ready === false || raw.length === 0) {
        setPerf({ kind: "hint", hint: hint || "暂无视频回收数据。请先在发布中心完成一次发布并触发数据回收，再回来生成选题建议。" })
      } else {
        setPerf({ kind: "suggestions", suggestions: raw })
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      toast({
        variant: "destructive",
        title: "表现数据读取失败",
        description: msg,
        dedupeKey: "ideas-performance-failed",
      })
    } finally {
      setPerfLoading(false)
    }
  }, [toast])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch("/api/v1/content-library/ideas", { cache: "no-store" })
      if (!res.ok) throw new Error(`接口返回 ${res.status}`)
      const data = await res.json()
      const raw = data?.result?.ideas
      setIdeas(Array.isArray(raw) ? (raw as Idea[]) : [])
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`选题库加载失败：${msg}`)
      toast({ variant: "destructive", title: "选题库加载失败", description: msg })
    } finally {
      setLoading(false)
    }
  }, [toast])

  const persist = useCallback(
    async (next: Idea[]) => {
      setSaving(true)
      try {
        const res = await fetch("/api/v1/content-library/ideas", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(next),
        })
        if (!res.ok) {
          const d = await res.json().catch(() => ({}))
          throw new Error(parseDetail(d?.detail))
        }
        setIdeas(next)
        return true
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        toast({ variant: "destructive", title: "选题保存失败", description: msg })
        return false
      } finally {
        setSaving(false)
      }
    },
    [toast],
  )

  useEffect(() => {
    void load()
  }, [load])

  const submit = async () => {
    const t = title.trim()
    if (!t) {
      toast({ variant: "destructive", title: "请填写选题标题" })
      return
    }
    const ok = await persist([
      { id: newId(), title: t, note: note.trim(), source: source.trim(), status: "pending", created: Math.floor(Date.now() / 1000) },
      ...ideas,
    ])
    if (ok) {
      setTitle("")
      setNote("")
      setSource("")
      setShowForm(false)
      toast({ title: "选题已加入", description: t })
    }
  }

  const cycleStatus = async (it: Idea) => {
    const idx = STATUSES.findIndex((s) => s.key === (it.status || "pending"))
    const next = STATUSES[(idx + 1) % STATUSES.length]
    await persist(ideas.map((x) => (x.id === it.id ? { ...x, status: next.key } : x)))
  }

  const remove = async (it: Idea) => {
    if (!confirm(`删除选题「${it.title}」？`)) return
    await persist(ideas.filter((x) => x.id !== it.id))
    toast({ title: "已删除", description: it.title })
  }

  const filtered = filter === "all" ? ideas : ideas.filter((i) => (i.status || "pending") === filter)
  const counts = FILTERS.map((f) => ({
    ...f,
    count: f.key === "all" ? ideas.length : ideas.filter((i) => (i.status || "pending") === f.key).length,
  }))

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · IDEAS"
        title="选题库"
        description="内容选题池：登记、跟踪与推进选题，一键送排期。"
        actions={
          <>
            <Button variant="ghost" onClick={load} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
              刷新
            </Button>
            <Button onClick={() => setShowForm((v) => !v)}>
              <Plus className="h-4 w-4" /> 新建选题
            </Button>
          </>
        }
      />

      <div className="mx-auto max-w-5xl space-y-5 px-6 py-6">
        <Card className="p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="space-y-1">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Flame className="h-4 w-4 text-primary" /> 从我的表现生成选题
              </div>
              <p className="text-xs text-muted-foreground">
                基于已发布视频的互动数据（播放 / 点赞 / 评论 / 收藏）反推选题方向。
              </p>
            </div>
            <Button onClick={() => void loadPerformance()} disabled={perfLoading}>
              {perfLoading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Sparkles className="h-4 w-4 mr-2" />}
              从我的表现生成
            </Button>
          </div>

          {perfLoading && (
            <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground" aria-live="polite">
              <Loader2 className="h-4 w-4 animate-spin" /> 正在读取你的视频表现…
            </div>
          )}

          {!perfLoading && perf?.kind === "hint" && (
            <div className="mt-3 flex items-start gap-2 rounded-md border border-border bg-accent/40 p-3 text-sm text-muted-foreground">
              <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
              <p>{perf.hint}</p>
            </div>
          )}

          {!perfLoading && perf?.kind === "suggestions" && perf.suggestions.length > 0 && (
            <div className="mt-3 space-y-2">
              {perf.suggestions.map((s, idx) => {
                const heat = clampHeat(s.heat)
                const pct = Math.round(heat * 100)
                return (
                  <div key={s.id ?? `${s.title}-${idx}`} className="rounded-md border border-border p-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 flex-1 space-y-1">
                        <p className="text-sm font-medium">{s.title}</p>
                        {s.note && <p className="text-xs text-muted-foreground">{s.note}</p>}
                      </div>
                      <div className="flex shrink-0 flex-col items-end gap-1">
                        <span className="font-mono text-xs text-muted-foreground">{pct}%</span>
                        <div
                          className="h-1.5 w-24 overflow-hidden rounded-full bg-muted"
                          role="progressbar"
                          aria-valuenow={pct}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-label={`热度 ${pct}%`}
                        >
                          <div
                            className="h-full rounded-full bg-primary"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </Card>

        {showForm && (
          <Card className="p-4">
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <NotebookPen className="h-4 w-4 text-primary" /> 新建选题
              </div>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="选题标题（必填）" />
              <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="选题说明：切入角度、参考案例、预期形式…" rows={3} />
              <div className="flex items-center gap-2">
                <Input value={source} onChange={(e) => setSource(e.target.value)} placeholder="来源（如：抖音热榜 / 竞品拆解）" className="flex-1" />
                <Button onClick={submit} disabled={saving || !title.trim()}>
                  <Send className="h-4 w-4" /> 保存选题
                </Button>
                <Button variant="outline" onClick={() => setShowForm(false)}>
                  取消
                </Button>
              </div>
            </div>
          </Card>
        )}

        {loading ? (
          <Card className="p-10 text-center text-muted-foreground">
            <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在读取选题库…
          </Card>
        ) : error ? (
          <Card className="p-10 text-center text-sm text-destructive">
            <TriangleAlert className="mx-auto mb-2 h-5 w-5" />
            <p>{error}</p>
            <Button className="mt-3" onClick={load}>重试</Button>
          </Card>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-1.5">
              {counts.map((f) => (
                <Button key={f.key} variant={filter === f.key ? "secondary" : "outline"} size="sm" onClick={() => setFilter(f.key)}>
                  {f.label}
                  <span className="ml-1 font-mono opacity-70">{f.count}</span>
                </Button>
              ))}
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
            </div>

            {ideas.length === 0 ? (
              <Card className="p-10 text-center text-sm text-muted-foreground">
                <NotebookPen className="mx-auto mb-2 h-5 w-5" />
                暂无数据。点击「新建选题」登记第一条。
              </Card>
            ) : filtered.length === 0 ? (
              <Card className="p-8 text-center text-sm text-muted-foreground">当前筛选下暂无数据。</Card>
            ) : (
              <div className="grid gap-3">
                {filtered.map((it) => {
                  const meta = statusMeta(it.status)
                  const Icon = meta.icon
                  return (
                    <Card key={it.id} className="p-4">
                      <div className="flex items-start gap-3">
                        <div className="min-w-0 flex-1 space-y-1.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <p className="text-sm font-medium">{it.title}</p>
                            {it.source && <Badge variant="outline" className="text-xs">来源：{it.source}</Badge>}
                          </div>
                          {it.note && <p className="text-xs text-muted-foreground">{it.note}</p>}
                          <p className="text-xs text-muted-foreground">登记：{fmtCreated(it.created)}</p>
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <Button variant="outline" size="sm" onClick={() => void cycleStatus(it)} disabled={saving}>
                            <Icon className="h-3.5 w-3.5" />
                            {meta.label}
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => void remove(it)} disabled={saving} aria-label="删除选题">
                            <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                          </Button>
                        </div>
                      </div>
                    </Card>
                  )
                })}
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              数据源：GET/POST /api/v1/content-library/ideas（磁盘直读 outputs/_ideas.json）
            </p>
          </>
        )}
      </div>
    </div>
  )
}
