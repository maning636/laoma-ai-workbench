"use client"

import { useEffect, useState } from "react"
import {
  BarChart3, RefreshCw, Loader2, Play, Code2, Database, Lightbulb,
} from "lucide-react"
import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { API_ENDPOINTS } from "@/lib/env"

interface Preset { question: string; title?: string }

export default function AnalyticsPage() {
  const [question, setQuestion] = useState("")
  const [presets, setPresets] = useState<Preset[]>([])
  const [querying, setQuerying] = useState(false)
  const [result, setResult] = useState<any>(null)
  const [source, setSource] = useState<string>("")

  const loadPresets = async () => {
    const r = await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/analytics/presets`)
    const d = await r.json()
    setPresets(d.presets || [])
  }

  const runQuery = async (q: string) => {
    setQuerying(true)
    setResult(null)
    try {
      const r = await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/analytics/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      })
      const d = await r.json()
      setResult(d)
      setSource(d.source || "")
    } catch (e) { console.error(e) } finally { setQuerying(false) }
  }

  useEffect(() => { loadPresets() }, [])

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="FUSION · P1"
        title="NL→SQL 数据分析"
        description="自然语言提问 → SQL → 图表数据 + 洞察（SELECT-only 安全）"
      />

      <div className="mx-auto max-w-6xl space-y-4 px-6 py-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />自然语言查询
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex gap-2">
              <Input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && question && runQuery(question)}
                placeholder="例如：近 30 天发布最多的账号是谁？"
              />
              <Button onClick={() => runQuery(question)} disabled={querying || !question}>
                {querying ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4 mr-1" />}
                查询
              </Button>
            </div>
            {presets.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {presets.map((p, i) => (
                  <Button key={i} size="sm" variant="outline"
                    onClick={() => { setQuestion(p.question); runQuery(p.question) }}>
                    {p.title || p.question}
                  </Button>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {result && (
          <div className="space-y-3">
            {result.sql && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Code2 className="h-4 w-4" />生成的 SQL
                    {source && <Badge variant="outline" className="ml-2">来源：{source}</Badge>}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <pre className="text-xs bg-muted p-3 rounded overflow-x-auto">{result.sql}</pre>
                </CardContent>
              </Card>
            )}

            {result.rows && (
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <Database className="h-4 w-4" />结果集（{result.rows.length} 行）
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b bg-muted/50">
                          {(result.columns || []).map((c: string) => (
                            <th key={c} className="text-left p-2 font-medium">{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {result.rows.map((row: any, i: number) => (
                          <tr key={i} className="border-b">
                            {(result.columns || []).map((c: string) => (
                              <td key={c} className="p-2">{row[c]}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}

            {result.insight && (
              <Card className="border-blue-200 bg-blue-50">
                <CardHeader className="pb-3">
                  <CardTitle className="text-sm flex items-center gap-2 text-blue-800">
                    <Lightbulb className="h-4 w-4" />洞察
                  </CardTitle>
                </CardHeader>
                <CardContent className="text-sm text-blue-900">{result.insight}</CardContent>
              </Card>
            )}
          </div>
        )}
      </div>
    </div>
  )
}