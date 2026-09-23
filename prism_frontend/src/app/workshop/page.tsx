"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Hammer, Loader2, Play, Wrench } from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/use-toast"

interface ToolParam {
  flag: string
  name: string
  type: "text" | "textarea" | "choice" | "number"
  label: string
  choices?: string[]
  default?: string
  required?: boolean
}

interface ToolInput {
  name: string
  label: string
  accept?: string
  required?: boolean
}

interface ToolSpec {
  id: string
  label: string
  group: string
  script: string
  subcommand: string
  desc: string
  inputs: ToolInput[]
  params: ToolParam[]
  outputs: Array<{ name: string; ext: string | null; label: string }>
}

interface RunResult {
  tool: string
  elapsed_seconds: number
  outputs: string[]
  file_ids: number[]
}

export default function WorkshopPage() {
  const { toast } = useToast()
  const [tools, setTools] = useState<ToolSpec[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<ToolSpec | null>(null)
  const [paramValues, setParamValues] = useState<Record<string, string>>({})
  const [inputFiles, setInputFiles] = useState<Record<string, File>>({})
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState("")
  const fileRefs = useRef<Record<string, HTMLInputElement | null>>({})

  const loadTools = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/v1/workshop/tools", { cache: "no-store" })
      const data = await res.json()
      setTools(data?.result?.tools || [])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadTools()
  }, [loadTools])

  const pickTool = (t: ToolSpec) => {
    setSelected(t)
    setResult(null)
    setError("")
    setInputFiles({})
    const defaults: Record<string, string> = {}
    t.params.forEach((p) => {
      if (p.default) defaults[p.name] = p.default
    })
    setParamValues(defaults)
  }

  const run = async () => {
    if (!selected) return
    // 校验必填
    for (const p of selected.params) {
      if (p.required && !paramValues[p.name]?.trim()) {
        toast({ variant: "destructive", title: `「${p.label}」为必填` })
        return
      }
    }
    for (const i of selected.inputs) {
      if (i.required && !inputFiles[i.name]) {
        toast({ variant: "destructive", title: `请上传「${i.label}」` })
        return
      }
    }

    setRunning(true)
    setError("")
    setResult(null)
    try {
      const form = new FormData()
      form.set("tool", selected.id)
      form.set("params", JSON.stringify(paramValues))
      for (const i of selected.inputs) {
        const f = inputFiles[i.name]
        if (f) form.append("files", f, f.name)
      }
      const res = await fetch("/api/v1/workshop/run", { method: "POST", body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data?.detail || "执行失败")
      setResult(data.result as RunResult)
      toast({ title: "执行完成", description: `产物已入库：file_id ${data.result.file_ids.join(", ")}` })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · WORKSHOP"
        title="创作工坊"
        description="Easel 产线工具的表单直调：确定性脚本执行，零 token 成本，产物自动入素材库。"
      />

      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        {loading ? (
          <Card className="p-10 text-center text-muted-foreground">
            <Loader2 className="mx-auto mb-2 h-5 w-5 animate-spin" /> 加载工具…
          </Card>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {tools.map((t) => (
              <Card
                key={t.id}
                className={`cursor-pointer p-4 transition ${selected?.id === t.id ? "border-primary" : "hover:border-primary/40"}`}
                onClick={() => pickTool(t)}
              >
                <div className="mb-1.5 flex items-center gap-2">
                  <Wrench className="h-4 w-4 text-primary" />
                  <span className="text-sm font-semibold">{t.label}</span>
                  <Badge variant="secondary" className="ml-auto text-xs">{t.group}</Badge>
                </div>
                <p className="line-clamp-2 text-xs text-muted-foreground">{t.desc}</p>
              </Card>
            ))}
          </div>
        )}

        {selected && (
          <Card className="p-5">
            <div className="mb-4 flex items-center gap-2">
              <Hammer className="h-4 w-4 text-primary" />
              <span className="text-sm font-semibold">{selected.label}</span>
              <Badge variant="outline" className="text-xs">{selected.script} · {selected.subcommand}</Badge>
            </div>

            <div className="space-y-4">
              {selected.inputs.map((i) => (
                <div key={i.name} className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">
                    {i.label}
                    {i.required && <span className="text-red-500"> *</span>}
                  </label>
                  <Input
                    ref={(el) => { fileRefs.current[i.name] = el }}
                    type="file"
                    accept={i.accept}
                    onChange={(e) => {
                      const f = e.target.files?.[0]
                      if (f) setInputFiles((prev) => ({ ...prev, [i.name]: f }))
                    }}
                  />
                  {inputFiles[i.name] && (
                    <div className="text-xs text-muted-foreground">已选：{inputFiles[i.name].name}</div>
                  )}
                </div>
              ))}

              {selected.params.map((p) => (
                <div key={p.name} className="space-y-1.5">
                  <label className="text-xs text-muted-foreground">
                    {p.label}
                    {p.required && <span className="text-red-500"> *</span>}
                  </label>
                  {p.type === "textarea" ? (
                    <Textarea
                      value={paramValues[p.name] || ""}
                      onChange={(e) => setParamValues((prev) => ({ ...prev, [p.name]: e.target.value }))}
                      className="min-h-[100px]"
                      placeholder="输入内容…"
                    />
                  ) : p.type === "choice" ? (
                    <select
                      value={paramValues[p.name] || p.default || ""}
                      onChange={(e) => setParamValues((prev) => ({ ...prev, [p.name]: e.target.value }))}
                      className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    >
                      {(p.choices || []).map((c) => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  ) : (
                    <Input
                      value={paramValues[p.name] || ""}
                      onChange={(e) => setParamValues((prev) => ({ ...prev, [p.name]: e.target.value }))}
                      placeholder={p.label}
                    />
                  )}
                </div>
              ))}

              <Button onClick={run} disabled={running} className="w-full">
                {running ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Play className="h-4 w-4 mr-2" />}
                {running ? "执行中…" : "执行"}
              </Button>
            </div>

            {error && (
              <div className="mt-4 rounded-lg border border-red-500/30 bg-red-500/5 p-3 text-sm text-red-600">
                {error}
              </div>
            )}

            {result && (
              <div className="mt-4 rounded-lg border bg-muted/20 p-4 space-y-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  执行完成
                  <Badge variant="secondary">{result.elapsed_seconds}s</Badge>
                </div>
                <div className="text-xs text-muted-foreground">
                  产物：{result.outputs.join(", ")}
                </div>
                <div className="text-xs text-muted-foreground">
                  已入素材库：file_id {result.file_ids.join(", ")} —
                  可在 <a className="underline" href="/materials" target="_blank">素材管理</a> 查看，
                  或到 <a className="underline" href="/easel-inbox" target="_blank">稿件箱</a> 流转发布
                </div>
              </div>
            )}
          </Card>
        )}
      </div>
    </div>
  )
}
