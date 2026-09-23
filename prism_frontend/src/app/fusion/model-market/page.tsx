"use client"

import { useEffect, useState } from "react"
import {
  Boxes, RefreshCw, Loader2, CheckCircle2, AlertCircle, KeyRound, Lightbulb,
} from "lucide-react"
import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { API_ENDPOINTS } from "@/lib/env"

interface Model {
  id: string
  name: string
  provider: string
  category?: string
  capabilities?: string[]
  price_note?: string
  description?: string
  context_window?: number
  modalities?: string[]
}

const USE_CASES = [
  { id: "writing", label: "内容创作" },
  { id: "reasoning", label: "深度推理" },
  { id: "batch", label: "批量生成" },
  { id: "multimodal", label: "多模态" },
  { id: "coding", label: "代码" },
  { id: "fast", label: "低延迟" },
]

export default function ModelMarketPage() {
  const [models, setModels] = useState<Model[]>([])
  const [keys, setKeys] = useState<Record<string, boolean>>({})
  const [recommend, setRecommend] = useState<any>(null)
  const [useCase, setUseCase] = useState("writing")
  const [search, setSearch] = useState("")
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    try {
      const [r1, r2] = await Promise.all([
        fetch(`${API_ENDPOINTS.base}/api/v1/fusion/model-market/models`),
        fetch(`${API_ENDPOINTS.base}/api/v1/fusion/model-market/api-keys`),
      ])
      const d1 = await r1.json()
      const d2 = await r2.json()
      setModels(d1.models || [])
      setKeys(d2.keys || {})
    } finally { setLoading(false) }
  }

  const loadRecommend = async (uc: string) => {
    setUseCase(uc)
    const r = await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/model-market/recommend?use_case=${uc}`)
    setRecommend(await r.json())
  }

  useEffect(() => { load(); loadRecommend("writing") }, [])

  const filtered = models.filter((m) =>
    search === "" ||
    m.name.toLowerCase().includes(search.toLowerCase()) ||
    m.id.toLowerCase().includes(search.toLowerCase()) ||
    m.provider.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="FUSION · P1"
        title="模型广场"
        description="所有模型能力对比、价格、标签、API Key 配置状态；按用例推荐"
        actions={
          <>
            <Input placeholder="搜索模型..." value={search}
              onChange={(e) => setSearch(e.target.value)} className="w-56" />
            <Button onClick={load} disabled={loading}>
              <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />刷新
            </Button>
          </>
        }
      />

      <div className="mx-auto max-w-6xl space-y-4 px-6 py-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Lightbulb className="h-4 w-4" />按用例推荐
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              {USE_CASES.map((uc) => (
                <Button key={uc.id} size="sm" variant={useCase === uc.id ? "default" : "outline"}
                  onClick={() => loadRecommend(uc.id)}>{uc.label}</Button>
              ))}
            </div>
            {recommend && (
              <div className="rounded-lg border p-4 bg-muted/30">
                <div className="flex items-center gap-2 mb-2">
                  <Boxes className="h-4 w-4" />
                  <span className="font-medium">推荐模型</span>
                  <Badge>{recommend.name || recommend.model_id}</Badge>
                </div>
                <div className="text-sm space-y-1">
                  {recommend.provider && <div>供应商：<span className="font-medium">{recommend.provider}</span></div>}
                  {recommend.reason && <div className="text-muted-foreground">理由：{recommend.reason}</div>}
                  {recommend.price_note && <div className="text-muted-foreground">价格：{recommend.price_note}</div>}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <KeyRound className="h-4 w-4" />API Key 配置状态
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {Object.entries(keys).map(([pid, configured]) => (
                <div key={pid} className="flex items-center gap-1.5 rounded-lg border px-3 py-1.5">
                  {configured
                    ? <CheckCircle2 className="h-4 w-4 text-green-600" />
                    : <AlertCircle className="h-4 w-4 text-muted-foreground" />}
                  <span className="text-sm">{pid}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Boxes className="h-4 w-4" />全部模型（{filtered.length}）
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading && models.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground">
                <Loader2 className="h-5 w-5 mr-2 animate-spin" />加载中...
              </div>
            ) : (
              <div className="space-y-2">
                {filtered.map((m) => {
                  const pid = m.provider
                  const configured = keys[pid] ?? false
                  return (
                    <div key={m.id} className="rounded-lg border p-3 hover:bg-muted/30">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-medium">{m.name}</span>
                            <Badge variant="outline" className="text-xs">{m.provider}</Badge>
                            {m.category && <Badge variant="secondary" className="text-xs">{m.category}</Badge>}
                            {configured ? (
                              <Badge className="text-xs"><CheckCircle2 className="h-3 w-3 mr-1" />已配置</Badge>
                            ) : (
                              <Badge variant="secondary" className="text-xs"><AlertCircle className="h-3 w-3 mr-1" />未配置</Badge>
                            )}
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            <code className="bg-muted px-1 py-0.5 rounded">{m.id}</code>
                            {m.context_window && <span className="ml-2">· {Math.floor(m.context_window / 1000)}K 上下文</span>}
                            {m.price_note && <span className="ml-2">· {m.price_note}</span>}
                          </div>
                          {m.capabilities && m.capabilities.length > 0 && (
                            <div className="mt-1.5 flex flex-wrap gap-1">
                              {m.capabilities.map((c, i) => (
                                <Badge key={i} variant="outline" className="text-xs">{c}</Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}