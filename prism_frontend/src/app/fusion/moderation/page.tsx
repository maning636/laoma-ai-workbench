"use client"

import { useEffect, useState } from "react"
import {
  Shield, RefreshCw, Loader2, CheckCircle2, XCircle, AlertTriangle, Plus, Trash2,
} from "lucide-react"
import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { API_ENDPOINTS } from "@/lib/env"

interface SensitiveWord { category: string; word: string }

interface ModerateResult {
  allowed: boolean
  level: "pass" | "warn" | "block"
  reason?: string
  layer1?: {
    matches: { word: string; category: string }[]
    has_block: boolean
  }
  layer2?: {
    allowed: boolean
    reason?: string
  }
  layer3?: {
    applied: boolean
    rewritten: string
  }
}

export default function ModerationPage() {
  const [content, setContent] = useState("这是一个包含敏感内容的示例：赌博、色情、暴力等。")
  const [enable1, setEnable1] = useState(true)
  const [enable2, setEnable2] = useState(true)
  const [enable3, setEnable3] = useState(true)
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState<ModerateResult | null>(null)
  const [words, setWords] = useState<SensitiveWord[]>([])
  const [newWord, setNewWord] = useState("")
  const [newCat, setNewCat] = useState("其他")
  const [loadingWords, setLoadingWords] = useState(false)

  const loadWords = async () => {
    setLoadingWords(true)
    try {
      const r = await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/moderation/sensitive-words`)
      const d = await r.json()
      setWords(d.words || [])
    } finally { setLoadingWords(false) }
  }

  useEffect(() => { loadWords() }, [])

  const check = async () => {
    setChecking(true)
    setResult(null)
    try {
      const r = await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/moderation/check`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content,
          enable_layer1: enable1,
          enable_layer2: enable2,
          enable_layer3: enable3,
        }),
      })
      setResult(await r.json())
    } catch (e) { console.error(e) } finally { setChecking(false) }
  }

  const addWord = async () => {
    if (!newWord) return
    await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/moderation/sensitive-words`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category: newCat, word: newWord }),
    })
    setNewWord("")
    loadWords()
  }

  const delWord = async (category: string, word: string) => {
    await fetch(
      `${API_ENDPOINTS.base}/api/v1/fusion/moderation/sensitive-words?category=${encodeURIComponent(category)}&word=${encodeURIComponent(word)}`,
      { method: "DELETE" }
    )
    loadWords()
  }

  const levelColor = (lvl: string) =>
    lvl === "pass" ? "text-green-600" : lvl === "warn" ? "text-orange-600" : "text-red-600"

  const levelIcon = (lvl: string) =>
    lvl === "pass" ? <CheckCircle2 className="h-5 w-5 text-green-600" /> :
    lvl === "warn" ? <AlertTriangle className="h-5 w-5 text-orange-600" /> :
    <XCircle className="h-5 w-5 text-red-600" />

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="FUSION · P0"
        title="三层内容审核"
        description="L1 敏感词本地检测 → L2 Qwen 语义审核 → L3 AI 合规改写"
      />

      <div className="mx-auto max-w-6xl space-y-4 px-6 py-6">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Shield className="h-4 w-4" />审核内容
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <Textarea value={content} onChange={(e) => setContent(e.target.value)}
              placeholder="输入要审核的内容..." className="min-h-[100px]" />
            <div className="flex items-center gap-6 flex-wrap">
              <label className="flex items-center gap-2 text-sm">
                <Checkbox checked={enable1} onCheckedChange={(v) => setEnable1(!!v)} />
                <Label>L1 敏感词</Label>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox checked={enable2} onCheckedChange={(v) => setEnable2(!!v)} />
                <Label>L2 语义审核</Label>
              </label>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox checked={enable3} onCheckedChange={(v) => setEnable3(!!v)} />
                <Label>L3 AI 改写</Label>
              </label>
              <Button onClick={check} disabled={checking || !content} className="ml-auto">
                {checking ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Shield className="h-4 w-4 mr-2" />}
                开始审核
              </Button>
            </div>
          </CardContent>
        </Card>

        {result && (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-3">
                {levelIcon(result.level)}
                <div>
                  <div className="text-lg font-semibold">{
                    result.level === "pass" ? "通过" : result.level === "warn" ? "警告" : "拦截"
                  }</div>
                  <div className="text-xs text-muted-foreground">{result.reason}</div>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              {result.layer1 && (
                <div className="rounded-lg border p-3">
                  <div className="text-xs font-medium mb-2">L1 敏感词检测</div>
                  {result.layer1.matches.length === 0 ? (
                    <div className="text-sm text-green-600 flex items-center gap-1">
                      <CheckCircle2 className="h-4 w-4" />无匹配
                    </div>
                  ) : (
                    <div className="flex flex-wrap gap-1">
                      {result.layer1.matches.map((m, i) => (
                        <Badge key={i} variant="outline" className={result.layer1.has_block ? "border-red-300 text-red-600" : "border-orange-300 text-orange-600"}>
                          {m.word} <span className="text-muted-foreground">· {m.category}</span>
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              )}
              {result.layer2 && (
                <div className="rounded-lg border p-3">
                  <div className="text-xs font-medium mb-2">L2 语义审核（Qwen）</div>
                  <div className={`text-sm flex items-center gap-1 ${levelColor(result.layer2.allowed ? "pass" : "block")}`}>
                    {result.layer2.allowed ? <CheckCircle2 className="h-4 w-4" /> : <XCircle className="h-4 w-4" />}
                    {result.layer2.allowed ? "通过" : "拒绝"}
                    {result.layer2.reason && <span className="text-muted-foreground ml-2">{result.layer2.reason}</span>}
                  </div>
                </div>
              )}
              {result.layer3 && result.layer3.applied && (
                <div className="rounded-lg border p-3">
                  <div className="text-xs font-medium mb-2">L3 AI 合规改写</div>
                  <div className="rounded bg-muted/50 p-3 text-sm">{result.layer3.rewritten}</div>
                </div>
              )}
            </CardContent>
          </Card>
        )}

        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Shield className="h-4 w-4" />敏感词库（{words.length} 条）
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex gap-2">
              <Input placeholder="新敏感词" value={newWord}
                onChange={(e) => setNewWord(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addWord()} />
              <select className="border rounded-md h-10 px-2 text-sm" value={newCat}
                onChange={(e) => setNewCat(e.target.value)}>
                <option>其他</option>
                <option>色情</option>
                <option>赌博</option>
                <option>暴力</option>
                <option>政治</option>
                <option>广告</option>
              </select>
              <Button onClick={addWord}>
                <Plus className="h-4 w-4 mr-1" />添加
              </Button>
              <Button variant="outline" onClick={loadWords} disabled={loadingWords}>
                {loadingWords ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              </Button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {words.map((w, i) => (
                <Badge key={i} variant="outline" className="group pr-1">
                  <span>{w.word} <span className="text-muted-foreground">· {w.category}</span></span>
                  <button onClick={() => delWord(w.category, w.word)}
                    className="ml-1 hover:text-red-600">
                    <Trash2 className="h-3 w-3" />
                  </button>
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}