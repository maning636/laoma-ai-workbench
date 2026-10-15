"use client"

import { useCallback, useEffect, useMemo, useState, type ComponentType, type SVGProps } from "react"
import {
  CalendarDays,
  CheckCircle2,
  Clock,
  Film,
  ListPlus,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Send,
  Trash2,
  TriangleAlert,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/use-toast"

interface ScheduleItem {
  id: string
  title: string
  date: string
  platform?: string
  time?: string
  status?: string
  note?: string
  kind?: "content" | "event"
  url?: string
  source?: string
}

const STATUS_META: Record<string, { label: string; icon: ComponentType<SVGProps<SVGSVGElement>>; variant: "secondary" | "outline" | "accent" | "destructive" | "default" }> = {
  idea: { label: "选题", icon: Clock, variant: "outline" },
  draft: { label: "起草中", icon: Film, variant: "secondary" },
  scheduled: { label: "已排期", icon: CalendarDays, variant: "accent" },
  published: { label: "已发布", icon: CheckCircle2, variant: "default" },
}

const DOW = ["一", "二", "三", "四", "五", "六", "日"]
const pad2 = (n: number) => String(n).padStart(2, "0")

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

export default function CalendarPage() {
  const { toast } = useToast()
  const [items, setItems] = useState<ScheduleItem[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<"calendar" | "list">("calendar")

  const today = useMemo(() => new Date(), [])
  const [cursor, setCursor] = useState<Date>(new Date(today.getFullYear(), today.getMonth(), 1))
  const [selectedDate, setSelectedDate] = useState<string>(() => {
    const d = new Date()
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
  })

  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<ScheduleItem | null>(null)
  const [title, setTitle] = useState("")
  const [date, setDate] = useState("")
  const [time, setTime] = useState("")
  const [platform, setPlatform] = useState("")
  const [status, setStatus] = useState("idea")
  const [note, setNote] = useState("")

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch("/api/v1/content-library/schedule", { cache: "no-store" })
      if (!res.ok) throw new Error(`接口返回 ${res.status}`)
      const data = await res.json()
      const raw = data?.result?.schedule
      setItems(Array.isArray(raw) ? (raw as ScheduleItem[]) : [])
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`排期加载失败：${msg}`)
      toast({ variant: "destructive", title: "排期加载失败", description: msg })
    } finally {
      setLoading(false)
    }
  }, [toast])

  const persist = useCallback(
    async (next: ScheduleItem[]) => {
      setSaving(true)
      try {
        const res = await fetch("/api/v1/content-library/schedule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(next),
        })
        if (!res.ok) {
          const d = await res.json().catch(() => ({}))
          throw new Error(parseDetail(d?.detail))
        }
        setItems(next)
        return true
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e)
        toast({ variant: "destructive", title: "排期保存失败", description: msg })
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

  const cells = useMemo(() => {
    const y = cursor.getFullYear()
    const m = cursor.getMonth()
    const first = new Date(y, m, 1)
    const startOffset = (first.getDay() + 6) % 7
    const dim = new Date(y, m + 1, 0).getDate()
    const out: { date: Date; inMonth: boolean }[] = []
    for (let i = 0; i < startOffset; i++) {
      const d = new Date(y, m, -startOffset + i)
      out.push({ date: d, inMonth: false })
    }
    for (let d = 1; d <= dim; d++) out.push({ date: new Date(y, m, d), inMonth: true })
    while (out.length % 7 !== 0) out.push({ date: new Date(y, m + 1, out.length - startOffset - dim + 1), inMonth: false })
    return out
  }, [cursor])

  const byDate = useMemo(() => {
    const map = new Map<string, ScheduleItem[]>()
    for (const it of items) {
      const k = String(it.date || "")
      if (!k) continue
      if (!map.has(k)) map.set(k, [])
      map.get(k)!.push(it)
    }
    for (const arr of map.values()) arr.sort((a, b) => (a.time || "").localeCompare(b.time || ""))
    return map
  }, [items])

  const dateKey = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
  const todayKey = dateKey(today)

  const openNew = (d?: string) => {
    setEditing(null)
    setTitle("")
    setDate(d || selectedDate || todayKey)
    setTime("")
    setPlatform("")
    setStatus("idea")
    setNote("")
    setShowForm(true)
  }

  const openEdit = (it: ScheduleItem) => {
    setEditing(it)
    setTitle(it.title || "")
    setDate(it.date || todayKey)
    setTime(it.time || "")
    setPlatform(it.platform || "")
    setStatus(it.status || "idea")
    setNote(it.note || "")
    setShowForm(true)
  }

  const submit = async () => {
    const t = title.trim()
    const d = date.trim().slice(0, 10)
    if (!t) return toast({ variant: "destructive", title: "请填写标题" })
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return toast({ variant: "destructive", title: "请选择日期", description: "格式 YYYY-MM-DD" })
    if (editing) {
      const ok = await persist(items.map((x) => (x.id === editing.id ? { ...x, title: t, date: d, time: time.trim(), platform: platform.trim(), status, note: note.trim() } : x)))
      if (ok) {
        setShowForm(false)
        setSelectedDate(d)
        toast({ title: "排期已更新", description: t })
      }
      return
    }
    const ok = await persist([{ id: newId(), title: t, date: d, time: time.trim(), platform: platform.trim(), status, note: note.trim(), source: "manual" }, ...items])
    if (ok) {
      setShowForm(false)
      setSelectedDate(d)
      toast({ title: "已加入排期", description: t })
    }
  }

  const moveToSchedule = async (ideaTitle: string) => {
    const d = selectedDate
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d)) return toast({ variant: "destructive", title: "请先在日历上选一个日期" })
    const ok = await persist([{ id: newId(), title: ideaTitle.trim(), date: d, time: "", platform: "", status: "idea", note: "由选题库转入", source: "ideas" }, ...items])
    if (ok) toast({ title: "已转入排期", description: `${ideaTitle.trim()} → ${d}` })
  }

  const sendToIdeas = async () => {
    try {
      const res = await fetch("/api/v1/content-library/ideas", { cache: "no-store" })
      const data = await res.json()
      const raw = data?.result?.ideas
      const ideas = Array.isArray(raw) ? raw as { title?: string }[] : []
      if (ideas.length === 0) {
        toast({ variant: "destructive", title: "选题库为空", description: "可前往「选题库」页先登记选题" })
        return
      }
      const first = ideas[0]
      if (!first?.title) return toast({ variant: "destructive", title: "首个选题缺少标题" })
      void moveToSchedule(first.title)
    } catch (e) {
      toast({ variant: "destructive", title: "读取选题库失败", description: e instanceof Error ? e.message : String(e) })
    }
  }

  const statusMeta = (s?: string) => STATUS_META[s || "idea"] || STATUS_META.idea

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · CALENDAR"
        title="排期日历"
        description="按日期安排内容发布与平台节点，支持从选题库一键转入排期。"
        actions={
          <>
            <Button variant="ghost" onClick={load} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
              刷新
            </Button>
            <Button variant="outline" onClick={sendToIdeas} disabled={saving}>
              <ListPlus className="h-4 w-4" /> 从选题转入
            </Button>
            <Button onClick={() => openNew()}>
              <Plus className="h-4 w-4" /> 新建排期
            </Button>
          </>
        }
      />

      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        {loading ? (
          <Card className="p-10 text-center text-muted-foreground">
            <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在读取排期…
          </Card>
        ) : error ? (
          <Card className="p-10 text-center text-sm text-destructive">
            <TriangleAlert className="mx-auto mb-2 h-5 w-5" />
            <p>{error}</p>
            <Button className="mt-3" onClick={load}>重试</Button>
          </Card>
        ) : (
          <>
            {showForm && (
              <Card className="p-4">
                <div className="space-y-3">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <CalendarDays className="h-4 w-4 text-primary" />
                    {editing ? "编辑排期" : "新建排期"}
                  </div>
                  <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="标题（必填）" />
                  <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
                    <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
                    <Input type="time" value={time} onChange={(e) => setTime(e.target.value)} />
                    <Input value={platform} onChange={(e) => setPlatform(e.target.value)} placeholder="平台（抖音/B站…）" />
                    <select
                      value={status}
                      onChange={(e) => setStatus(e.target.value)}
                      className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                    >
                      {Object.entries(STATUS_META).map(([k, v]) => (
                        <option key={k} value={k}>{v.label}</option>
                      ))}
                    </select>
                  </div>
                  <Textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder="备注" />
                  <div className="flex items-center gap-2">
                    <Button onClick={submit} disabled={saving || !title.trim()}>
                      <Save className="h-4 w-4" /> {editing ? "保存修改" : "加入排期"}
                    </Button>
                    <Button variant="outline" onClick={() => setShowForm(false)}>取消</Button>
                    {editing && (
                      <Button variant="ghost" className="text-destructive" onClick={() => void persist(items.filter((x) => x.id !== editing.id))} disabled={saving}>
                        <Trash2 className="h-4 w-4" /> 删除
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            )}

            <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
              <Card className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Button variant="outline" size="sm" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))} aria-label="上个月">
                      ‹
                    </Button>
                    <span className="min-w-[7rem] text-center text-sm font-medium">
                      {cursor.getFullYear()} 年 {cursor.getMonth() + 1} 月
                    </span>
                    <Button variant="outline" size="sm" onClick={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))} aria-label="下个月">
                      ›
                    </Button>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => setCursor(new Date(today.getFullYear(), today.getMonth(), 1))}>今天</Button>
                </div>
                <div className="grid grid-cols-7 gap-1">
                  {DOW.map((d) => (
                    <div key={d} className="pb-1 text-center text-xs text-muted-foreground">周{d}</div>
                  ))}
                  {cells.map((c) => {
                    const key = dateKey(c.date)
                    const list = byDate.get(key) || []
                    const isSel = key === selectedDate
                    const isToday = key === todayKey
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setSelectedDate(key)}
                        onDoubleClick={() => openNew(key)}
                        className={[
                          "flex min-h-[4.5rem] flex-col items-stretch gap-0.5 rounded-md border p-1.5 text-left transition",
                          c.inMonth ? "bg-background" : "opacity-40",
                          isSel ? "border-primary bg-primary/10" : "border-border/60 hover:border-primary/50",
                        ].join(" ")}
                      >
                        <div className="flex items-center justify-between">
                          <span className={["text-xs font-medium", isToday ? "flex h-5 w-5 items-center justify-center rounded-full bg-primary text-primary-foreground" : ""].join(" ")}>
                            {c.date.getDate()}
                          </span>
                          {list.length > 0 && <span className="text-xs text-primary">{list.length}</span>}
                        </div>
                        {list.slice(0, 2).map((it) => {
                          const M = statusMeta(it.status)
                          const Icon = M.icon
                          return (
                            <div key={it.id} className="flex items-center gap-1 truncate rounded bg-muted px-1 py-0.5 text-[11px]" title={it.title}>
                              <Icon className="h-3 w-3 shrink-0 text-muted-foreground" />
                              <span className="truncate">{it.title}</span>
                            </div>
                          )
                        })}
                      </button>
                    )
                  })}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">双击日期可快速新建；点击日期查看当日详情。</p>
              </Card>

              <Card className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-sm font-medium">
                    {selectedDate} · {(byDate.get(selectedDate) || []).length} 项
                  </span>
                  <Button variant="outline" size="sm" onClick={() => openNew(selectedDate)}>
                    <Plus className="h-3.5 w-3.5" /> 当日新增
                  </Button>
                </div>
                {(byDate.get(selectedDate) || []).length === 0 ? (
                  <div className="py-8 text-center text-xs text-muted-foreground">这一天还没有排期。</div>
                ) : (
                  <div className="space-y-2">
                    {(byDate.get(selectedDate) || []).map((it) => {
                      const M = statusMeta(it.status)
                      const Icon = M.icon
                      return (
                        <div key={it.id} className="flex items-start gap-2 rounded-lg border p-2.5">
                          <Icon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm">{it.title}</p>
                            <div className="mt-1 flex flex-wrap items-center gap-1.5">
                              <Badge variant={M.variant} className="text-xs">{M.label}</Badge>
                              {it.time && <Badge variant="outline" className="font-mono text-xs">{it.time}</Badge>}
                              {it.platform && <Badge variant="outline" className="text-xs">{it.platform}</Badge>}
                            </div>
                            {it.note && <p className="mt-1 text-xs text-muted-foreground">{it.note}</p>}
                          </div>
                          <Button variant="ghost" size="sm" onClick={() => openEdit(it)} aria-label="编辑">
                            <Send className="h-3.5 w-3.5 text-muted-foreground" />
                          </Button>
                        </div>
                      )
                    })}
                  </div>
                )}
              </Card>
            </div>

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <Button variant={view === "calendar" ? "secondary" : "outline"} size="sm" onClick={() => setView("calendar")}>
                  <CalendarDays className="h-3.5 w-3.5" /> 日历视图
                </Button>
                <Button variant={view === "list" ? "secondary" : "outline"} size="sm" onClick={() => setView("list")}>
                  清单视图
                </Button>
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
              </div>
              <p className="text-xs text-muted-foreground">数据源：GET/POST /api/v1/content-library/schedule（outputs/_schedule.json）</p>
            </div>

            {view === "list" && (
              items.length === 0 ? (
                <Card className="p-10 text-center text-sm text-muted-foreground">
                  <CalendarDays className="mx-auto mb-2 h-5 w-5" />
                  暂无数据。点击「新建排期」或「从选题转入」添加第一条。
                </Card>
              ) : (
                <Card className="p-0">
                  <CardContent className="p-0">
                    {[...items]
                      .sort((a, b) => `${a.date} ${a.time || ""}`.localeCompare(`${b.date} ${b.time || ""}`))
                      .map((it) => {
                        const M = statusMeta(it.status)
                        const Icon = M.icon
                        return (
                          <div key={it.id} className="flex items-center gap-3 border-b border-border/50 px-4 py-2.5 last:border-0">
                            <span className="font-mono text-xs text-muted-foreground">{it.date}</span>
                            {it.time && <span className="font-mono text-xs text-muted-foreground">{it.time}</span>}
                            <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                            <span className="min-w-0 flex-1 truncate text-sm">{it.title}</span>
                            {it.platform && <Badge variant="outline" className="text-xs">{it.platform}</Badge>}
                            <Badge variant={M.variant} className="text-xs">{M.label}</Badge>
                            <Button variant="ghost" size="sm" onClick={() => openEdit(it)} aria-label="编辑">
                              <Send className="h-3.5 w-3.5 text-muted-foreground" />
                            </Button>
                          </div>
                        )
                      })}
                  </CardContent>
                </Card>
              )
            )}
          </>
        )}
      </div>
    </div>
  )
}
