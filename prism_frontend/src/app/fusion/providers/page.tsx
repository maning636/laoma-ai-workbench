"use client"

import { useEffect, useState } from "react"
import {
  Database, RefreshCw, Loader2, CheckCircle2, AlertCircle, KeyRound,
} from "lucide-react"
import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { API_ENDPOINTS } from "@/lib/env"

interface Provider {
  id: string
  name: string
  base_url: string
  default_model: string
  env_key: string
  price_note?: string
  api_key_configured: boolean
  models?: Record<string, string>
}

interface DetectInfo {
  provider: string | null
  name: string | null
  base_url: string | null
  model: string | null
  error?: string
}

export default function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([])
  const [detect, setDetect] = useState<DetectInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState("")

  const load = async () => {
    setLoading(true)
    try {
      const [r1, r2] = await Promise.all([
        fetch(`${API_ENDPOINTS.base}/api/v1/fusion/providers`),
        fetch(`${API_ENDPOINTS.base}/api/v1/fusion/providers/detect`),
      ])
      const d1 = await r1.json()
      const d2 = await r2.json()
      setProviders(d1.providers || [])
      setDetect(d2)
    } catch (e) {
      console.error("加载 Provider 失败", e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const filtered = providers.filter((p) =>
    search === "" ||
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.id.includes(search.toLowerCase()) ||
    (p.default_model || "").toLowerCase().includes(search.toLowerCase())
  )

  const configuredCount = providers.filter((p) => p.api_key_configured).length

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="FUSION · P0"
        title="AI 多 Provider 注册表"
        description="统一管理所有 LLM 供应商，按 PROBE_ORDER 自动探测已配置的 API Key"
        actions={
          <>
            <Input
              placeholder="搜索 provider / 模型..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-56"
            />
            <Button onClick={load} disabled={loading}>
              <RefreshCw className={`h-4 w-4 mr-2 ${loading ? "animate-spin" : ""}`} />
              刷新
            </Button>
          </>
        }
      />

      <div className="mx-auto max-w-6xl space-y-4 px-6 py-6">
        <Card>
          <CardContent className="pt-4 grid grid-cols-4 gap-4">
            <div>
              <div className="text-xs text-muted-foreground">已注册供应商</div>
              <div className="text-2xl font-semibold">{providers.length}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">已配置 API Key</div>
              <div className="text-2xl font-semibold text-green-600">{configuredCount}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">未配置</div>
              <div className="text-2xl font-semibold text-muted-foreground">
                {providers.length - configuredCount}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">当前探测到</div>
              <div className="text-lg font-semibold flex items-center gap-1.5">
                {detect?.provider ? (
                  <><CheckCircle2 className="h-4 w-4 text-green-600" />{detect.name}</>
                ) : (
                  <><AlertCircle className="h-4 w-4 text-orange-500" />未配置</>
                )}
              </div>
            </div>
          </CardContent>
        </Card>

        {detect && detect.error && (
          <Card className="border-orange-300 bg-orange-50">
            <CardContent className="pt-4 text-sm text-orange-700">
              <AlertCircle className="h-4 w-4 inline mr-1" />
              {detect.error}
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Database className="h-4 w-4" />
              所有供应商
            </CardTitle>
          </CardHeader>
          <CardContent>
            {loading && providers.length === 0 ? (
              <div className="flex items-center justify-center py-12 text-muted-foreground">
                <Loader2 className="h-5 w-5 mr-2 animate-spin" /> 加载中...
              </div>
            ) : (
              <div className="space-y-2">
                {filtered.map((p) => (
                  <div key={p.id} className="rounded-lg border p-3 hover:bg-muted/30">
                    <div className="flex items-start gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium">{p.name}</span>
                          <Badge variant="outline" className="text-xs">{p.id}</Badge>
                          {p.api_key_configured ? (
                            <Badge variant="default" className="text-xs">
                              <CheckCircle2 className="h-3 w-3 mr-1" />已配置
                            </Badge>
                          ) : (
                            <Badge variant="secondary" className="text-xs">
                              <AlertCircle className="h-3 w-3 mr-1" />未配置
                            </Badge>
                          )}
                        </div>
                        <div className="mt-1.5 text-xs text-muted-foreground space-y-0.5">
                          <div>
                            默认模型：<code className="bg-muted px-1 py-0.5 rounded">{p.default_model}</code>
                            {p.models && (
                              <span className="ml-2">· {Object.keys(p.models).length} 个可选</span>
                            )}
                          </div>
                          <div>
                            环境变量：<code className="bg-muted px-1 py-0.5 rounded">
                              <KeyRound className="h-3 w-3 inline mr-1" />
                              {p.env_key}
                            </code>
                            {" · "}
                            <span className="text-muted-foreground/70">{p.base_url}</span>
                          </div>
                          {p.price_note && (
                            <div className="text-muted-foreground/60">{p.price_note}</div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
                {filtered.length === 0 && !loading && (
                  <div className="py-8 text-center text-muted-foreground text-sm">
                    无匹配供应商
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}