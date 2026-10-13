"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import Link from "next/link"
import {
  ArrowRight,
  Bookmark,
  Check,
  Copy,
  Eye,
  Flame,
  FolderOpen,
  Heart,
  Layers,
  Loader2,
  MessageCircle,
  Package,
  Pen,
  RefreshCw,
  Search,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet"

interface OutputNode {
  name: string
  path: string
  mtime: number
  fileCount?: number
  meta?: { title?: string; platform?: string; cover?: string }
}

type SkillLayer = "discover" | "plan" | "produce" | "publish" | "attribute" | "general"

interface SkillItem {
  name: string
  dir: string
  description: string
  layer: SkillLayer
  layer_label: string
  version: string
  author: string
  scripts: number
  files: number
  mtime: number
}

interface SkillCatalog {
  total: number
  total_all: number
  layers: Partial<Record<SkillLayer, number>>
  items: SkillItem[]
  updated_at: number
  source_dir: string
}

interface SkillListEnvelope {
  status?: string
  result?: SkillCatalog
}

const LAYER_TABS: Array<{ id: SkillLayer; label: string }> = [
  { id: "produce", label: "创作" },
  { id: "plan", label: "策划" },
  { id: "discover", label: "发现" },
  { id: "publish", label: "发布" },
  { id: "attribute", label: "归因" },
  { id: "general", label: "通用" },
]

const LAYER_BADGE_CLASS: Record<SkillLayer, string> = {
  discover: "bg-sky-500/15 text-sky-400",
  plan: "bg-violet-500/15 text-violet-400",
  produce: "bg-emerald-500/15 text-emerald-400",
  publish: "bg-amber-500/15 text-amber-400",
  attribute: "bg-rose-500/15 text-rose-400",
  general: "bg-muted text-muted-foreground",
}

function buildSkillPrompt(skill: SkillItem): string {
  const desc = skill.description.trim().replace(/\s+/g, " ").slice(0, 80)
  const layerLabel = skill.layer_label || "创作"
  const body = [
    `【技能】${skill.name}`,
    `【分类】${layerLabel}`,
    `【概述】${desc}`,
    "",
    "请把以下工作交给这个技能完成，并输出可直接进入工作台的下一步动作：",
    "1. 明确本次产出目标与验收标准；",
    "2. 调用该技能并展示执行计划；",
    "3. 完成后汇总关键产物与后续建议。",
  ].join("\n")
  return body
}

interface HotItem {
  title: string
  source?: string
  url?: string
}

interface RecentWork {
  id: string
  title: string
  thumbnail: string
  videoUrl: string
  publishDate: string
  playCount: number
  likeCount: number
  commentCount: number
  collectCount: number
}

interface PlatformMetrics {
  totalPlays: number
  totalLikes: number
  totalComments: number
}

interface PlatformData extends PlatformMetrics {
  deltas: {
    plays: number | null
    likes: number | null
    comments: number | null
  }
  works: RecentWork[]
}

type PlatformKey = "bilibili" | "douyin"

interface PlatformCardConfig {
  key: PlatformKey
  label: string
  badge: string
  badgeClass: string
}

const PLATFORM_CARDS: PlatformCardConfig[] = [
  {
    key: "bilibili",
    label: "B 站",
    badge: "BILI",
    badgeClass: "bg-blue-500/15 text-blue-400",
  },
  {
    key: "douyin",
    label: "抖音",
    badge: "DY",
    badgeClass: "bg-rose-500/15 text-rose-400",
  },
]

const QUICK_LINKS = [
  { href: "/skills", label: "技能库", desc: "113 个创作技能浏览与详情", icon: Layers },
  { href: "/easel-content", label: "内容库", desc: "创作产物全量浏览与预览", icon: FolderOpen },
  { href: "/easel-inbox", label: "稿件箱", desc: "稿件导入素材库并创建投放计划", icon: Package },
]

function toISODate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`
}

function toNum(v: unknown): number {
  if (typeof v === "number") return Number.isFinite(v) ? v : 0
  if (typeof v === "string") {
    const n = Number(v)
    return Number.isFinite(n) ? n : 0
  }
  return 0
}

function toDateStr(v: unknown): string {
  if (v == null) return ""
  if (typeof v === "string") return v.length >= 10 ? v.slice(0, 10) : v
  if (v instanceof Date) return toISODate(v)
  return ""
}

function formatNumber(n: number): string {
  const abs = Math.abs(n)
  if (abs >= 1e8) return (n / 1e8).toFixed(2).replace(/\.?0+$/, "") + " 亿"
  if (abs >= 1e4) return (n / 1e4).toFixed(2).replace(/\.?0+$/, "") + " 万"
  if (abs >= 1000) return Math.round(n).toLocaleString("en-US")
  return Math.round(n).toString()
}

function formatDelta(v: number | null): string {
  if (v == null) return "—"
  const abs = Math.abs(v)
  const suffix = abs >= 1000 ? abs.toFixed(0) : abs.toFixed(1)
  return `${v >= 0 ? "+" : ""}${suffix}%`
}

function deltaClassName(v: number | null): string {
  if (v == null) return "text-muted-foreground"
  if (v > 0.05) return "text-emerald-400"
  if (v < -0.05) return "text-rose-400"
  return "text-muted-foreground"
}

interface AnalyticsWindow {
  totalPlays: number
  totalLikes: number
  totalComments: number
}

async function fetchAnalyticsWindow(platform: PlatformKey, start: string, end: string): Promise<AnalyticsWindow | null> {
  try {
    const qs = new URLSearchParams({
      startDate: start,
      endDate: end,
      platforms: platform,
      limit: "200",
    })
    const res = await fetch(`/api/v1/analytics/?${qs.toString()}`, { cache: "no-store" })
    if (!res.ok) return null
    const data: unknown = await res.json()
    const obj = data as { summary?: Record<string, unknown>; videos?: Record<string, unknown>[] }
    const summary = obj.summary ?? {}
    return {
      totalPlays: toNum(summary.totalPlays),
      totalLikes: toNum(summary.totalLikes),
      totalComments: toNum(summary.totalComments),
    }
  } catch {
    return null
  }
}

function toRecentWork(v: Record<string, unknown>): RecentWork {
  return {
    id: String(v.videoId ?? v.id ?? ""),
    title: String(v.title ?? ""),
    thumbnail: String(v.thumbnail ?? ""),
    videoUrl: String(v.videoUrl ?? ""),
    publishDate: toDateStr(v.publishDate),
    playCount: toNum(v.playCount),
    likeCount: toNum(v.likeCount),
    commentCount: toNum(v.commentCount),
    collectCount: toNum(v.collectCount),
  }
}

async function fetchPlatformData(platform: PlatformKey): Promise<PlatformData | null> {
  const today = new Date()
  const curStart = new Date(today)
  curStart.setDate(today.getDate() - 6)
  const prevEnd = new Date(today)
  prevEnd.setDate(today.getDate() - 7)
  const prevStart = new Date(today)
  prevStart.setDate(today.getDate() - 13)

  const [current, prev, res] = await Promise.all([
    fetchAnalyticsWindow(platform, toISODate(curStart), toISODate(today)),
    fetchAnalyticsWindow(platform, toISODate(prevStart), toISODate(prevEnd)),
    fetch(`/api/v1/analytics/?platform=${platform}&limit=6`, { cache: "no-store" }),
  ])

  if (!current) return null

  let works: RecentWork[] = []
  if (res.ok) {
    try {
      const data: unknown = await res.json()
      const rawWorks = (data as { videos?: unknown }).videos
      if (Array.isArray(rawWorks)) {
        works = rawWorks
          .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
          .map(toRecentWork)
      }
    } catch {
      works = []
    }
  }

  const currentMetrics: PlatformMetrics = {
    totalPlays: current.totalPlays,
    totalLikes: current.totalLikes,
    totalComments: current.totalComments,
  }

  const computeDelta = (cur: number, prev: number): number | null => {
    if (!prev) return cur > 0 ? 100 : null
    return ((cur - prev) / prev) * 100
  }

  const deltas = {
    plays: computeDelta(current.totalPlays, prev?.totalPlays ?? 0),
    likes: computeDelta(current.totalLikes, prev?.totalLikes ?? 0),
    comments: computeDelta(current.totalComments, prev?.totalComments ?? 0),
  }

  return { ...currentMetrics, deltas, works }
}

function Delta({ value }: { value: number | null }) {
  return (
    <span className={`text-xs font-medium ${deltaClassName(value)}`}>
      {formatDelta(value)}
    </span>
  )
}

function StatTile({
  icon: Icon,
  label,
  value,
  delta,
  accentClass,
}: {
  icon: typeof Eye
  label: string
  value: number
  delta: number | null
  accentClass: string
}) {
  return (
    <div className="rounded-lg border bg-muted/30 p-3">
      <div className="flex items-center gap-1.5">
        <Icon className={`h-3.5 w-3.5 ${accentClass}`} />
        <span className="text-xs text-muted-foreground">{label}</span>
      </div>
      <div className="mt-2 text-lg font-semibold tab-nums">{formatNumber(value)}</div>
      <div className="mt-1 flex items-center justify-between">
        <span className="text-xs text-muted-foreground">近 7 日环比</span>
        <Delta value={delta} />
      </div>
    </div>
  )
}

function WorksList({ works }: { works: RecentWork[] }) {
  if (works.length === 0) {
    return <div className="text-xs text-muted-foreground">暂无最近作品</div>
  }
  return (
    <div className="space-y-2">
      {works.slice(0, 5).map((w, i) => (
        <Link
          key={w.id || `${w.title}-${i}`}
          href={w.videoUrl || "#"}
          target={w.videoUrl ? "_blank" : undefined}
          rel={w.videoUrl ? "noreferrer" : undefined}
          className="flex items-center gap-3 rounded-md border p-2 transition hover:border-primary/40"
        >
          <div className="h-10 w-16 shrink-0 overflow-hidden rounded-md bg-muted">
            {w.thumbnail ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={w.thumbnail} alt="" className="h-full w-full object-cover" loading="lazy" />
            ) : (
              <div className="flex h-full items-center justify-center text-muted-foreground">
                <FolderOpen className="h-4 w-4" />
              </div>
            )}
          </div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm">{w.title || "（未命名作品）"}</div>
            <div className="mt-0.5 flex items-center gap-3 text-xs text-muted-foreground">
              {w.publishDate && <span>{w.publishDate}</span>}
              <span className="inline-flex items-center gap-1"><Eye className="h-3 w-3" />{formatNumber(w.playCount)}</span>
              <span className="inline-flex items-center gap-1"><Heart className="h-3 w-3" />{formatNumber(w.likeCount)}</span>
              <span className="inline-flex items-center gap-1"><MessageCircle className="h-3 w-3" />{formatNumber(w.commentCount)}</span>
            </div>
          </div>
        </Link>
      ))}
    </div>
  )
}

function PlatformCard({ config, data, loading }: { config: PlatformCardConfig; data: PlatformData | null; loading: boolean }) {
  if (loading) {
    return (
      <Card className="p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Badge className={config.badgeClass}>{config.badge}</Badge>
          {config.label}
          <Loader2 className="ml-auto h-3.5 w-3.5 animate-spin text-muted-foreground" />
        </div>
        <div className="py-8 text-center text-xs text-muted-foreground">加载中…</div>
      </Card>
    )
  }

  if (!data) {
    return (
      <Card className="p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-medium">
          <Badge className={config.badgeClass}>{config.badge}</Badge>
          {config.label}
        </div>
        <div className="py-8 text-center text-xs text-muted-foreground">数据暂不可用</div>
      </Card>
    )
  }

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2 text-sm font-medium">
        <Badge className={config.badgeClass}>{config.badge}</Badge>
        {config.label}
        <span className="text-xs font-normal text-muted-foreground">· 近 7 日环比</span>
        <span className="ml-auto text-xs text-muted-foreground">{data.works.length} 个作品</span>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <StatTile icon={Eye} label="播放" value={data.totalPlays} delta={data.deltas.plays} accentClass="text-sky-400" />
        <StatTile icon={Heart} label="点赞" value={data.totalLikes} delta={data.deltas.likes} accentClass="text-rose-400" />
        <StatTile icon={MessageCircle} label="评论" value={data.totalComments} delta={data.deltas.comments} accentClass="text-amber-400" />
      </div>
      <div className="mt-4 border-t pt-3">
        <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
          <Bookmark className="h-3 w-3" /> 最近作品
        </div>
        <WorksList works={data.works} />
      </div>
    </Card>
  )
}

export default function WorkbenchPage() {
  const [catalog, setCatalog] = useState<{ total: number; total_files: number; items: OutputNode[] } | null>(null)
  const [hottopic, setHottopic] = useState<HotItem[]>([])
  const [loading, setLoading] = useState(true)
  const [hotLoading, setHotLoading] = useState(false)
  const [analyticsState, setAnalyticsState] = useState<Record<PlatformKey, { loading: boolean; data: PlatformData | null }>>({
    bilibili: { loading: true, data: null },
    douyin: { loading: true, data: null },
  })

  // 能力菜单（技能库）抽屉状态
  const [sheetOpen, setSheetOpen] = useState(false)
  const [skillCatalog, setSkillCatalog] = useState<SkillCatalog | null>(null)
  const [skillLoading, setSkillLoading] = useState(true)
  const [skillError, setSkillError] = useState(false)
  const [skillRefreshing, setSkillRefreshing] = useState(false)
  const [skillLayer, setSkillLayer] = useState<SkillLayer>("produce")
  const [skillKeyword, setSkillKeyword] = useState("")
  const [copiedPrompt, setCopiedPrompt] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/v1/content-library", { cache: "no-store" })
      const data = await res.json()
      setCatalog(data?.result || null)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadHot = useCallback(async () => {
    setHotLoading(true)
    try {
      // 复用 老马AI工作台 保留的 fusion 热点 API（顶层为 平台→条目数组 字典）
      const res = await fetch("/api/v1/fusion/hot-topics/all", { cache: "no-store" })
      const data = await res.json()
      const items: HotItem[] = []
      for (const [src, list] of Object.entries(data || {})) {
        if (!Array.isArray(list)) continue
        for (const it of list) {
          const obj = typeof it === "string" ? { title: it } : (it as Record<string, unknown>)
          const title = String((obj.title as string) || "").trim()
          const note = String((obj.note as string) || "")
          if (!title) continue
          if (note.includes("不可用") || note.includes("抓取")) continue // 占位失败项
          items.push({ title, source: (obj.source as string) || src })
        }
        if (items.length >= 12) break
      }
      setHottopic(items)
    } catch {
      setHottopic([])
    } finally {
      setHotLoading(false)
    }
  }, [])

  const loadAnalytics = useCallback(async () => {
    setAnalyticsState({
      bilibili: { loading: true, data: null },
      douyin: { loading: true, data: null },
    })
    for (const platform of PLATFORM_CARDS) {
      const data = await fetchPlatformData(platform.key)
      setAnalyticsState((prev) => ({
        ...prev,
        [platform.key]: { loading: false, data },
      }))
    }
  }, [])

  const refreshAll = useCallback(() => {
    void load()
    void loadHot()
    void loadAnalytics()
  }, [load, loadHot, loadAnalytics])

  // --- 能力菜单（技能库）---
  const loadSkills = useCallback(async () => {
    setSkillLoading(true)
    setSkillError(false)
    try {
      const params = new URLSearchParams()
      if (skillLayer) params.set("layer", skillLayer)
      const res = await fetch(`/api/v1/skills?${params.toString()}`, { cache: "no-store" })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: SkillListEnvelope = await res.json()
      setSkillCatalog(data.result ?? null)
    } catch {
      setSkillCatalog(null)
      setSkillError(true)
    } finally {
      setSkillLoading(false)
    }
  }, [skillLayer])

  // 抽屉首次打开、或切换分层时重取；keyword 走本地过滤，避免每次按键都发请求
  useEffect(() => {
    if (!sheetOpen) return
    void loadSkills()
  }, [sheetOpen, loadSkills])

  const refreshSkills = useCallback(async () => {
    setSkillRefreshing(true)
    try {
      await fetch("/api/v1/skills/refresh", { method: "POST" })
      await loadSkills()
    } finally {
      setSkillRefreshing(false)
    }
  }, [loadSkills])

  const filteredSkills: SkillItem[] = useMemo(() => {
    const base = skillCatalog?.items ?? []
    const kw = skillKeyword.trim().toLowerCase()
    if (!kw) return base
    return base.filter((s) => {
      return s.name.toLowerCase().includes(kw) || s.description.toLowerCase().includes(kw)
    })
  }, [skillCatalog, skillKeyword])

  const handleCopyPrompt = useCallback(async (skill: SkillItem) => {
    const prompt = buildSkillPrompt(skill)
    try {
      await navigator.clipboard.writeText(prompt)
      setCopiedPrompt(skill.name)
      window.setTimeout(() => {
        setCopiedPrompt((prev) => (prev === skill.name ? null : prev))
      }, 1600)
    } catch {
      // 剪贴板权限受限（如非安全上下文），静默失败
    }
  }, [])

  useEffect(() => {
    void load()
    void loadHot()
    void loadAnalytics()
  }, [load, loadHot, loadAnalytics])

  const recent = (catalog?.items || []).slice(0, 9)

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · WORKBENCH"
        title="创作工作台"
        description="产线总览：内容资产、今日热点、创作数据与各入口快捷导航。"
        actions={
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => setSheetOpen(true)} title="能力菜单">
              <Pen className="h-4 w-4 mr-2" /> 能力
            </Button>
            <Button variant="ghost" onClick={refreshAll} disabled={loading}>
              {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
              刷新
            </Button>
          </div>
        }
      />

      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        <div className="grid grid-cols-3 gap-3">
          <Card className="p-4 text-center">
            <div className="text-xl font-semibold">{loading ? "—" : (catalog?.total ?? 0)}</div>
            <div className="text-xs text-muted-foreground">内容项目</div>
          </Card>
          <Card className="p-4 text-center">
            <div className="text-xl font-semibold">{loading ? "—" : (catalog?.total_files ?? 0)}</div>
            <div className="text-xs text-muted-foreground">产物文件</div>
          </Card>
          <Card className="p-4 text-center">
            <div className="text-xl font-semibold">{loading ? "—" : (catalog?.items?.[0]?.mtime ? new Date(catalog.items[0].mtime * 1000).toLocaleDateString("zh-CN") : "—")}</div>
            <div className="text-xs text-muted-foreground">最近更新</div>
          </Card>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          {QUICK_LINKS.map((q) => {
            const Icon = q.icon
            return (
              <Link key={q.href} href={q.href}>
                <Card className="h-full cursor-pointer p-4 transition hover:border-primary/40 hover:shadow-md">
                  <div className="flex items-center gap-2">
                    <Icon className="h-4 w-4 text-primary" />
                    <span className="text-sm font-medium">{q.label}</span>
                    <ArrowRight className="ml-auto h-4 w-4 text-muted-foreground" />
                  </div>
                  <p className="mt-1.5 text-xs text-muted-foreground">{q.desc}</p>
                </Card>
              </Link>
            )
          })}
        </div>

        <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
          <Card className="p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-medium">
              <Flame className="h-4 w-4 text-orange-500" /> 今日热点
              {hotLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
            </div>
            {hottopic.length === 0 ? (
              <div className="text-xs text-muted-foreground">暂无热点数据（热点聚合接口未返回）。</div>
            ) : (
              <div className="space-y-1.5">
                {hottopic.slice(0, 10).map((h, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    {h.source && <Badge variant="outline" className="shrink-0 text-xs">{h.source}</Badge>}
                    <span className="truncate">{h.title}</span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-medium">最近产物</span>
              <Link href="/easel-content" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
                全部内容库 <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
            {loading ? (
              <div className="py-6 text-center text-xs text-muted-foreground">
                <Loader2 className="mx-auto mb-2 h-4 w-4 animate-spin" /> 加载中…
              </div>
            ) : recent.length === 0 ? (
              <div className="py-6 text-center text-xs text-muted-foreground">还没有产物。</div>
            ) : (
              <div className="space-y-2">
                {recent.map((n) => (
                  <Link key={n.path} href="/easel-content" className="flex items-center gap-3 rounded-lg border p-2.5 transition hover:border-primary/40">
                    <div className="h-10 w-10 shrink-0 overflow-hidden rounded-md bg-muted">
                      {n.meta?.cover ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={`/api/v1/content-library/media?path=${encodeURIComponent(n.meta.cover)}`} alt="" className="h-full w-full object-cover" loading="lazy" />
                      ) : (
                        <div className="flex h-full items-center justify-center text-muted-foreground"><FolderOpen className="h-4 w-4" /></div>
                      )}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm">{n.meta?.title || n.name}</div>
                      <div className="text-xs text-muted-foreground">{n.fileCount} 文件</div>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </div>

        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Bookmark className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-medium">创作数据</h2>
            <span className="text-xs text-muted-foreground">· 近 7 日环比与最近作品</span>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {PLATFORM_CARDS.map((c) => (
              <PlatformCard
                key={c.key}
                config={c}
                data={analyticsState[c.key].data}
                loading={analyticsState[c.key].loading}
              />
            ))}
          </div>
        </div>

        <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
          <SheetContent side="right" className="w-full sm:max-w-xl gap-3 p-5">
            <SheetHeader>
              <div className="flex items-center gap-2">
                <Pen className="h-4 w-4 text-primary" />
                <SheetTitle>能力菜单</SheetTitle>
                {skillCatalog && (
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    共 {skillCatalog.total_all} 个技能
                  </span>
                )}
              </div>
              <SheetDescription>
                按分层浏览并复用技能。选定后推荐起始提示词会自动写入剪贴板，回到工作台对话即可粘贴。
              </SheetDescription>
            </SheetHeader>

            <div className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                value={skillKeyword}
                onChange={(e) => setSkillKeyword(e.target.value)}
                placeholder="搜索技能名称 / 描述…"
                className="pl-9"
                aria-label="搜索技能"
              />
            </div>

            <div className="flex flex-wrap gap-1.5">
              {LAYER_TABS.map((t) => {
                const active = skillLayer === t.id
                return (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setSkillLayer(t.id)}
                    className={`rounded-full border px-3 py-1 text-xs transition ${
                      active
                        ? "border-primary bg-primary/10 text-foreground"
                        : "border-border/70 text-muted-foreground hover:bg-muted/30"
                    }`}
                  >
                    {t.label}
                    <span className="ml-1 text-[10px] opacity-80">
                      {skillCatalog?.layers?.[t.id] ?? 0}
                    </span>
                  </button>
                )
              })}
            </div>

            <div className="mt-2 flex-1 overflow-y-auto pr-1">
              {skillLoading && !skillCatalog ? (
                <div className="flex flex-col items-center justify-center py-10 text-xs text-muted-foreground">
                  <Loader2 className="mb-2 h-4 w-4 animate-spin" />
                  加载中…
                </div>
              ) : skillError && !skillCatalog ? (
                <div className="rounded-lg border border-dashed p-5 text-center text-xs text-muted-foreground">
                  <div className="mb-2 text-sm font-medium text-foreground">技能库暂不可用</div>
                  <p className="mb-3">
                    无法从 <code>/api/v1/skills</code> 拉取数据，请检查后端服务是否启动。
                  </p>
                  <Button size="sm" variant="outline" onClick={() => void refreshSkills()} disabled={skillRefreshing}>
                    {skillRefreshing ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5 mr-1" />
                    )}
                    重新扫描
                  </Button>
                </div>
              ) : filteredSkills.length === 0 ? (
                <div className="py-10 text-center text-xs text-muted-foreground">
                  没有匹配的技能。换个关键词试试？
                </div>
              ) : (
                <div className="space-y-2">
                  {filteredSkills.map((s) => {
                    const active = copiedPrompt === s.name
                    return (
                      <button
                        key={s.dir || s.name}
                        type="button"
                        onClick={() => void handleCopyPrompt(s)}
                        className="w-full rounded-lg border p-3 text-left transition hover:border-primary/40 hover:bg-muted/20"
                      >
                        <div className="flex items-start gap-2">
                          <span className="text-sm font-medium">
                            {s.layer_label || "通用"}·{s.name}
                          </span>
                          <Badge className={`ml-auto shrink-0 text-[10px] ${LAYER_BADGE_CLASS[s.layer] ?? "bg-muted"}`}>
                            {s.layer_label || "通用"}
                          </Badge>
                        </div>
                        <div className="mt-0.5 truncate text-xs text-muted-foreground">{s.name}</div>
                        <div className="mt-1 line-clamp-1 text-xs text-muted-foreground/90">
                          {s.description || "（无描述）"}
                        </div>
                        <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground">
                          <span className="inline-flex items-center gap-1">
                            {active ? (
                              <Check className="h-3 w-3 text-emerald-400" />
                            ) : (
                              <Copy className="h-3 w-3" />
                            )}
                            {active ? "已复制到剪贴板" : "复制起始提示词"}
                          </span>
                          {s.scripts > 0 && <span>{s.scripts} 脚本</span>}
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
            </div>

            <div className="flex items-center justify-between border-t pt-3 text-xs text-muted-foreground">
              <span>点选技能将推荐起始提示词复制到剪贴板</span>
              <Button size="sm" variant="ghost" onClick={() => void refreshSkills()} disabled={skillRefreshing}>
                {skillRefreshing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin mr-1" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5 mr-1" />
                )}
                刷新
              </Button>
            </div>
          </SheetContent>
        </Sheet>
      </div>
    </div>
  )
}
