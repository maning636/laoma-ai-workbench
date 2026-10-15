"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { Boxes, Loader2, RefreshCw, Search, Sparkles } from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

interface SkillItem {
  name: string
  dir: string
  description: string
  layer: string
  layer_label: string
  version: string
  author: string
  scripts: number
  files: number
  mtime: number
  body?: string
}

interface Catalog {
  total: number
  total_all: number
  layers: Record<string, number>
  items: SkillItem[]
  source_dir: string
}

const LAYER_TABS: Array<{ id: string; label: string }> = [
  { id: "", label: "全部" },
  { id: "produce", label: "创作" },
  { id: "plan", label: "策划" },
  { id: "discover", label: "发现" },
  { id: "publish", label: "发布" },
  { id: "attribute", label: "归因" },
  { id: "general", label: "通用" },
]

const LAYER_COLORS: Record<string, "default" | "secondary" | "outline" | "destructive" | "accent"> = {
  produce: "default",
  plan: "secondary",
  discover: "outline",
  publish: "outline",
  attribute: "outline",
  general: "secondary",
}

export default function SkillsPage() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [layer, setLayer] = useState("")
  const [keyword, setKeyword] = useState("")
  const [detail, setDetail] = useState<SkillItem | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (layer) params.set("layer", layer)
      if (keyword.trim()) params.set("keyword", keyword.trim())
      const res = await fetch(`/api/v1/skills?${params.toString()}`, { cache: "no-store" })
      const data = await res.json()
      setCatalog(data?.result || null)
    } catch {
      setCatalog(null)
    } finally {
      setLoading(false)
    }
  }, [layer, keyword])

  useEffect(() => {
    const t = setTimeout(() => void load(), keyword ? 300 : 0)
    return () => clearTimeout(t)
  }, [load, keyword])

  const refresh = async () => {
    setRefreshing(true)
    try {
      await fetch("/api/v1/skills/refresh", { method: "POST" })
      await load()
    } finally {
      setRefreshing(false)
    }
  }

  const openDetail = async (name: string) => {
    setDetailLoading(true)
    setDetail({ name } as SkillItem)
    try {
      const res = await fetch(`/api/v1/skills/${encodeURIComponent(name)}`, { cache: "no-store" })
      const data = await res.json()
      if (data?.result) setDetail(data.result)
    } finally {
      setDetailLoading(false)
    }
  }

  const stats = useMemo(() => catalog?.layers || {}, [catalog])

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · SKILL REGISTRY"
        title="技能库"
        description="AI 融合技能注册中心。技能源目录实时扫描，更新后点刷新即生效。"
        actions={
          <Button variant="ghost" onClick={refresh} disabled={refreshing}>
            <RefreshCw className="h-4 w-4 mr-2" /> 重新扫描
          </Button>
        }
      />

      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
          <Card className="p-3 text-center">
            <div className="text-lg font-semibold">{catalog?.total_all ?? "—"}</div>
            <div className="text-xs text-muted-foreground">技能总数</div>
          </Card>
          {LAYER_TABS.filter((t) => t.id).map((t) => (
            <Card key={t.id} className="p-3 text-center">
              <div className="text-lg font-semibold">{stats[t.id] ?? 0}</div>
              <div className="text-xs text-muted-foreground">{t.label}</div>
            </Card>
          ))}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex flex-wrap gap-1.5">
            {LAYER_TABS.map((t) => (
              <button
                key={t.id}
                onClick={() => setLayer(t.id)}
                className={`rounded-lg border px-3 py-1.5 text-xs transition ${layer === t.id ? "border-primary bg-primary/10 text-foreground" : "text-muted-foreground hover:bg-muted/30"}`}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className="relative ml-auto w-full sm:w-64">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              placeholder="搜索技能名称/描述…"
              className="pl-8"
            />
          </div>
        </div>

        {loading ? (
          <Card className="p-10 text-center text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2" /> 正在扫描技能…
          </Card>
        ) : !catalog || catalog.total === 0 ? (
          <Card className="p-10 text-center">
            <Boxes className="h-8 w-8 mx-auto mb-3 text-muted-foreground" />
            <div className="text-sm">没有匹配的技能</div>
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
            {catalog.items.map((s) => (
              <Card
                key={s.dir}
                className="cursor-pointer p-4 transition hover:border-primary/40 hover:shadow-md"
                onClick={() => openDetail(s.name)}
              >
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Sparkles className="h-4 w-4 shrink-0 text-primary" />
                    <span className="truncate text-sm font-semibold">{s.name}</span>
                  </div>
                  <Badge variant={LAYER_COLORS[s.layer] || "outline"} className="shrink-0 text-xs">
                    {s.layer_label}
                  </Badge>
                </div>
                <p className="line-clamp-3 text-xs leading-relaxed text-muted-foreground">{s.description}</p>
                <div className="mt-2 flex items-center gap-2 text-xs text-muted-foreground">
                  {s.scripts > 0 && (
                    <Badge variant="secondary" className="text-xs">🐍 {s.scripts} 脚本</Badge>
                  )}
                  <span>{s.files} 个文件</span>
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      <Dialog open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
        <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              {detail?.name}
              {detail?.layer_label && <Badge variant="secondary">{detail.layer_label}</Badge>}
              {detail?.scripts ? <Badge variant="outline">🐍 {detail.scripts} 脚本</Badge> : null}
            </DialogTitle>
          </DialogHeader>
          {detailLoading ? (
            <div className="py-10 text-center text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mx-auto" />
            </div>
          ) : (
            <div className="space-y-4">
              {detail?.description && (
                <p className="text-sm leading-relaxed text-muted-foreground">{detail.description}</p>
              )}
              <div className="rounded-lg border bg-muted/20 p-4">
                <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">
                  {detail?.body || "（无正文）"}
                </pre>
              </div>
              {detail?.author && (
                <div className="text-xs text-muted-foreground">
                  作者：{detail.author} {detail.version ? `· v${detail.version}` : ""}
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
