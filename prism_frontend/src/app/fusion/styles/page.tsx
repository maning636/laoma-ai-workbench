"use client"

import { useEffect, useState } from "react"
import {
  Palette, RefreshCw, Loader2, ExternalLink, Sparkles, Save, Trash2,
} from "lucide-react"
import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { API_ENDPOINTS } from "@/lib/env"

interface Style {
  name: string
  tone: string
  opening: string
  closing: string
  max_word_count: number
  emoji_policy: string
  structure_hint: string
  title_style: string
  tags_max: number
  cover_aspect: string
  platform_specific?: string
}

export default function StylesPage() {
  const [styles, setStyles] = useState<Record<string, Style>>({})
  const [loading, setLoading] = useState(true)
  const [active, setActive] = useState<string>("zhihu")
  const [sample, setSample] = useState("这是一个通用的示例内容，需要针对不同平台做差异化调整。")
  const [applyResult, setApplyResult] = useState<any>(null)
  const [applying, setApplying] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const r = await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/platform-styles`)
      const d = await r.json()
      setStyles(d.styles || {})
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const apply = async () => {
    setApplying(true)
    setApplyResult(null)
    try {
      const r = await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/platform-styles/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: sample, platform: active }),
      })
      setApplyResult(await r.json())
    } catch (e) {
      console.error(e)
    } finally { setApplying(false) }
  }

  const reset = async (platform: string) => {
    await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/platform-styles/${platform}`, {
      method: "DELETE",
    })
    load()
  }

  const platforms = Object.keys(styles)

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="FUSION · P0"
        title="平台差异化风格"
        description="7 家平台的语气、结构、emoji、封面规则；支持前台修改与套用"
        actions={<Button onClick={load} disabled={loading}>
          <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />刷新
        </Button>}
      />

      <div className="mx-auto max-w-6xl space-y-4 px-6 py-6">
        {loading && platforms.length === 0 ? (
          <div className="flex items-center justify-center py-12 text-muted-foreground">
            <Loader2 className="h-5 w-5 mr-2 animate-spin" />加载中...
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {platforms.map((key) => {
              const s = styles[key]
              const isActive = key === active
              return (
                <Card key={key} className={`cursor-pointer p-4 transition-all ${isActive ? "border-primary" : "hover:bg-muted/30"}`}
                  onClick={() => setActive(key)}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Palette className="h-4 w-4 text-primary" />
                      <span className="font-medium">{s.name}</span>
                      <Badge variant="outline">{key}</Badge>
                    </div>
                    <div className="flex items-center gap-1">
                      <Badge variant="secondary" className="text-xs">≤{s.max_word_count} 字</Badge>
                    </div>
                  </div>
                  <div className="space-y-1.5 text-xs text-muted-foreground">
                    <div><span className="font-medium text-foreground">语气：</span>{s.tone}</div>
                    <div><span className="font-medium text-foreground">结构：</span>{s.structure_hint}</div>
                    <div><span className="font-medium text-foreground">emoji：</span>{s.emoji_policy}</div>
                    <div><span className="font-medium text-foreground">标签：</span>≤{s.tags_max} · <span className="font-medium text-foreground">封面：</span>{s.cover_aspect}</div>
                  </div>
                  <div className="mt-2 flex items-center justify-between pt-2 border-t">
                    <span className="text-xs text-muted-foreground italic">"
                      {s.opening.slice(0, 30)}{s.opening.length > 30 ? "..." : ""}"</span>
                    <Button size="sm" variant="ghost" onClick={(e) => { e.stopPropagation(); reset(key) }}>
                      <Trash2 className="h-3 w-3" />重置
                    </Button>
                  </div>
                </Card>
              )
            })}
          </div>
        )}

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Sparkles className="h-4 w-4" />套用当前平台风格（{styles[active]?.name}）
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea
              value={sample}
              onChange={(e) => setSample(e.target.value)}
              placeholder="输入内容..."
              className="min-h-[100px]"
            />
            <div className="flex items-center gap-2">
              <Button onClick={apply} disabled={applying || !sample}>
                <Save className="h-4 w-4 mr-2" />套用
                {styles[active]?.name}风格
              </Button>
              {applying && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            </div>
            {applyResult && (
              <div className="rounded-lg border p-3 bg-muted/30">
                <div className="text-xs text-muted-foreground mb-2">
                  已生成 · 目标平台：<Badge>{styles[active]?.name}</Badge>
                </div>
                <pre className="text-sm whitespace-pre-wrap break-all">
                  {JSON.stringify(applyResult, null, 2)}
                </pre>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}