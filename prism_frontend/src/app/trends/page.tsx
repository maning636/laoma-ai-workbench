"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  ExternalLink,
  Flame,
  Loader2,
  RefreshCw,
  TriangleAlert,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useToast } from "@/components/ui/use-toast"

interface TrendItem {
  title: string
  heat_score?: number
  rank?: number
  source?: string
  platform?: string
  url?: string
  note?: string
  fetched_at?: string
}

type TrendData = Record<string, TrendItem[]>

const PLATFORMS = [
  { key: "weibo", label: "微博" },
  { key: "toutiao", label: "今日头条" },
  { key: "douyin", label: "抖音" },
  { key: "zhihu", label: "知乎" },
  { key: "xiaohongshu", label: "小红书" },
]

const FILTERS = [
  { key: "all", label: "全部" },
  { key: "real", label: "仅有效热度" },
  { key: "fallback", label: "兜底条目" },
] as const

type FilterKey = (typeof FILTERS)[number]["key"]

function fmtHeat(n: number | undefined): string {
  if (n === undefined || n === null || n <= 0) return "—"
  if (n >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (n >= 1e4) return `${(n / 1e4).toFixed(1)}万`
  return Math.round(n).toString()
}

function fmtTime(ts?: string): string {
  if (!ts) return "—"
  const d = new Date(ts.includes(" ") ? ts.replace(" ", "T") : ts)
  return Number.isNaN(d.getTime()) ? ts : d.toLocaleString("zh-CN", { hour12: false })
}

export default function TrendsPage() {
  const { toast } = useToast()
  const [data, setData] = useState<TrendData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<FilterKey>("all")

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch("/api/v1/fusion/hot-topics/all", { cache: "no-store" })
      if (!res.ok) throw new Error(`接口返回 ${res.status}`)
      const data = await res.json()
      if (!data || typeof data !== "object") throw new Error("接口返回格式异常")
      setData(data as TrendData)
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`热榜加载失败：${msg}`)
      toast({ variant: "destructive", title: "热榜加载失败", description: msg })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void load()
  }, [load])

  const entries = useMemo(() => {
    return PLATFORMS.map((p) => {
      const raw = data?.[p.key] || []
      const items = raw.filter((it) => String(it?.title || "").trim())
      const fallback = items.filter((it) => !(it.heat_score && it.heat_score > 0))
      return {
        ...p,
        total: items.length,
        real: items.length - fallback.length,
        items,
        fallback,
      }
    })
  }, [data])

  const visibleEntries = useMemo(() => {
    if (filter === "real") return entries.map((e) => ({ ...e, items: e.items.filter((it) => it.heat_score && it.heat_score > 0) }))
    if (filter === "fallback") return entries.map((e) => ({ ...e, items: e.fallback }))
    return entries
  }, [entries, filter])

  const totalEntries = entries.reduce((n, e) => n + e.total, 0)
  const validPlatforms = entries.filter((e) => e.real > 0).length
  const latestFetched = useMemo(() => {
    const times = entries.flatMap((e) => e.items.map((it) => it.fetched_at)).filter(Boolean).sort()
    return times[times.length - 1]
  }, [entries])

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · TRENDS"
        title="趋势热榜"
        description="多平台实时热榜聚合：微博、今日头条、抖音（知乎/小红书为诚实兜底占位）。"
        actions={
          <Button variant="ghost" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
            刷新
          </Button>
        }
      />

      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        {loading ? (
          <Card className="p-10 text-center text-muted-foreground">
            <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" /> 正在拉取多平台热榜…
          </Card>
        ) : error ? (
          <Card className="p-10 text-center text-sm text-destructive">
            <TriangleAlert className="mx-auto mb-2 h-5 w-5" />
            <p>{error}</p>
            <Button className="mt-3" onClick={load}>重试</Button>
          </Card>
        ) : totalEntries === 0 ? (
          <Card className="p-10 text-center text-sm text-muted-foreground">暂无数据。</Card>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-3">
              <Card className="p-4 text-center">
                <div className="text-xl font-semibold">{totalEntries}</div>
                <div className="text-xs text-muted-foreground">热榜条目总数</div>
              </Card>
              <Card className="p-4 text-center">
                <div className="text-xl font-semibold">
                  {validPlatforms}/{PLATFORMS.length}
                </div>
                <div className="text-xs text-muted-foreground">有真实热度的平台</div>
              </Card>
              <Card className="p-4 text-center">
                <div className="text-xl font-semibold">{latestFetched ? fmtTime(latestFetched).slice(5, 16) : "—"}</div>
                <div className="text-xs text-muted-foreground">最近抓取</div>
              </Card>
            </div>

            <div className="flex flex-wrap items-center gap-1.5">
              {FILTERS.map((f) => (
                <Button key={f.key} variant={filter === f.key ? "secondary" : "outline"} size="sm" onClick={() => setFilter(f.key)}>
                  {f.label}
                </Button>
              ))}
              <span className="ml-2 text-xs text-muted-foreground">
                数据源：GET /api/v1/fusion/hot-topics/all
              </span>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              {visibleEntries.map((e) => (
                <Card key={e.key} className="p-0">
                  <div className="flex items-center justify-between border-b border-border/70 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <Flame className="h-4 w-4 text-orange-500" />
                      <span className="text-sm font-medium">{e.label}</span>
                      {e.real === 0 ? (
                        <Badge variant="outline" className="text-xs">兜底占位 · 无真实热度</Badge>
                      ) : (
                        <Badge variant="accent" className="text-xs">{e.real} 条有效</Badge>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground">{e.items.length} 条</span>
                  </div>
                  <CardContent className="p-0">
                    {e.items.length === 0 ? (
                      <div className="px-4 py-6 text-center text-xs text-muted-foreground">暂无数据。</div>
                    ) : (
                      <div className="max-h-[52vh] overflow-y-auto">
                        {e.items.map((it, i) => {
                          const noHeat = !it.heat_score || it.heat_score <= 0
                          const rank = it.rank && it.rank > 0 ? it.rank : i + 1
                          return (
                            <div key={`${it.title}-${i}`} className="flex items-start gap-3 border-b border-border/40 px-4 py-2.5 last:border-0">
                              <div className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs font-medium">{rank}</div>
                              <div className="min-w-0 flex-1">
                                <p className="text-sm leading-snug">{it.title}</p>
                                {noHeat && it.note && (
                                  <p className="mt-0.5 text-xs text-muted-foreground/80">{it.note}</p>
                                )}
                              </div>
                              <div className="flex shrink-0 items-center gap-1.5">
                                <Badge variant={noHeat ? "outline" : "secondary"} className="font-mono text-xs">
                                  {noHeat ? "—" : fmtHeat(it.heat_score)}
                                </Badge>
                                {it.url && (
                                  <a href={it.url} target="_blank" rel="noreferrer" title="打开原链接">
                                    <ExternalLink className="h-3.5 w-3.5 text-muted-foreground hover:text-foreground" />
                                  </a>
                                )}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </CardContent>
                </Card>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
