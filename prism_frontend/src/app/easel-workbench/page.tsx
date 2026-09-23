"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import {
  ArrowRight,
  Flame,
  FolderOpen,
  Layers,
  Loader2,
  Package,
  RefreshCw,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

interface OutputNode {
  name: string
  path: string
  mtime: number
  fileCount?: number
  meta?: { title?: string; platform?: string; cover?: string }
}

interface HotItem {
  title: string
  source?: string
  url?: string
}

const QUICK_LINKS = [
  { href: "/skills", label: "技能库", desc: "113 个创作技能浏览与详情", icon: Layers },
  { href: "/easel-content", label: "内容库", desc: "创作产物全量浏览与预览", icon: FolderOpen },
  { href: "/easel-inbox", label: "稿件箱", desc: "稿件导入素材库并创建投放计划", icon: Package },
]

export default function WorkbenchPage() {
  const [catalog, setCatalog] = useState<{ total: number; total_files: number; items: OutputNode[] } | null>(null)
  const [hottopic, setHottopic] = useState<HotItem[]>([])
  const [loading, setLoading] = useState(true)
  const [hotLoading, setHotLoading] = useState(false)

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
      // 复用 Prism 保留的 fusion 热点 API（顶层为 平台→条目数组 字典）
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

  useEffect(() => {
    void load()
    void loadHot()
  }, [load, loadHot])

  const recent = (catalog?.items || []).slice(0, 9)

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · WORKBENCH"
        title="创作工作台"
        description="产线总览：内容资产、今日热点与各入口快捷导航。"
        actions={
          <Button variant="ghost" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
            刷新
          </Button>
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
      </div>
    </div>
  )
}
