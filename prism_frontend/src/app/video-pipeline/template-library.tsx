"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Loader2, Play, Search, LayoutGrid, Eye, ExternalLink } from "lucide-react"

import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { useToast } from "@/components/ui/use-toast"

interface TemplateItem {
  id: string
  name: string
  description: string
  category: string
  tags: string[]
  duration?: number
  size?: string
}
interface SchemaField {
  id: string
  label?: string
  type?: string
  default?: string | number | boolean
  options?: { value: string; label?: string }[]
}
interface TemplateDetail extends TemplateItem {
  schema: SchemaField[]
  dir: string
  exists: boolean
  preview?: string | null
}

const LIB_PREVIEW_BASE = "http://127.0.0.1:4312"  // E:\FDE\fde-landing-delivery 的 http.server

export function TemplateLibrary() {
  const { toast } = useToast()
  const [templates, setTemplates] = useState<TemplateItem[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [category, setCategory] = useState("全部")
  const [q, setQ] = useState("")
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<TemplateDetail | null>(null)
  const [values, setValues] = useState<Record<string, string>>({})
  const [rendering, setRendering] = useState(false)
  const [renderResult, setRenderResult] = useState<{ outputs: string[]; file_ids: number[]; elapsed: number } | null>(null)
  const [selLoading, setSelLoading] = useState(false)
  const previewRef = useRef<HTMLIFrameElement>(null)
  const [templateHtml, setTemplateHtml] = useState<string>("")
  const [srcdoc, setSrcdoc] = useState<string>("")
  const htmlCache = useRef<Record<string, string>>({})
  const srcdocTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const loadTemplates = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (category && category !== "全部") params.set("category", category)
      if (q.trim()) params.set("q", q.trim())
      const res = await fetch(`/api/v1/video-pipeline/templates?${params}`, { cache: "no-store" })
      const data = await res.json()
      if (data?.status === "success") {
        setTemplates(data.result.templates)
        setCategories(data.result.categories)
      }
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [category, q])

  useEffect(() => { void loadTemplates() }, [loadTemplates])

  const selectTemplate = async (id: string) => {
    setSelLoading(true)
    setRenderResult(null)
    try {
      const res = await fetch(`/api/v1/video-pipeline/templates/${encodeURIComponent(id)}`, { cache: "no-store" })
      const data = await res.json()
      if (data?.status === "success") {
        const d = data.result as TemplateDetail
        setSelected(d)
        // 用 schema 默认值初始化表单
        const init: Record<string, string> = {}
        for (const f of d.schema || []) init[f.id] = String(f.default ?? "")
        setValues(init)
      }
    } catch { /* ignore */ }
    finally { setSelLoading(false) }
  }

  const render = async () => {
    if (!selected) return
    setRendering(true)
    setRenderResult(null)
    try {
      // 只填非空 + 非默认的变量（减少传输）
      const vars: Record<string, unknown> = {}
      for (const f of selected.schema || []) {
        const v = values[f.id]
        if (v !== undefined && v !== "" && v !== String(f.default ?? "")) {
          vars[f.id] = f.type === "number" ? Number(v) : v
        }
      }
      const form = new FormData()
      form.append("composition_dir", selected.dir)
      form.append("quality", "standard")
      form.append("fps", "30")
      if (Object.keys(vars).length) form.append("variables", JSON.stringify(vars))
      const res = await fetch("/api/v1/video-pipeline/render", { method: "POST", body: form })
      const data = await res.json()
      if (!res.ok || data?.status !== "success") throw new Error(data?.detail || `渲染失败 (${res.status})`)
      setRenderResult({ outputs: data.result.outputs, file_ids: data.result.file_ids, elapsed: data.result.elapsed_seconds })
      toast({ title: "渲染完成", description: `${data.result.outputs.join(", ")} 已入素材库` })
    } catch (e) {
      toast({ title: "渲染失败", description: e instanceof Error ? e.message : String(e), variant: "destructive" })
    } finally { setRendering(false) }
  }

  // 复刻 live-preview.js：注入 window.__hyperframes 变量 + 播放脚本，srcdoc 挂进 iframe
  const buildSrcdoc = useCallback((html: string, vars: Record<string, string>) => {
    if (!html) return ""
    const varsScript = `<script>window.__hyperframes={getVariables:function(){return ${JSON.stringify(vars)};}};</script>`
    const player = `<script>window.addEventListener("load",function(){var tls=Object.values(window.__timelines||{});tls.forEach(function(tl){try{tl.repeat&&tl.repeat(-1);tl.repeatDelay&&tl.repeatDelay(0.4);tl.play&&tl.play(0);}catch(e){}});});</script>`
    let out = html
    if (/<head[^>]*>/i.test(out)) {
      out = out.replace(/<head[^>]*>/i, (m) => m + varsScript)
      out = /<\/head>/i.test(out) ? out.replace(/<\/head>/i, player + "</head>") : out
    } else if (/<html[^>]*>/i.test(out)) {
      out = out.replace(/<html[^>]*>/i, (m) => m + varsScript)
      out = out + player
    } else {
      out = varsScript + out + player
    }
    return out
  }, [])

  // 选模板时 fetch html（同源代理，规避 4312 跨域）
  useEffect(() => {
    if (!selected) { setTemplateHtml(""); setSrcdoc(""); return }
    const id = selected.id
    if (htmlCache.current[id]) { setTemplateHtml(htmlCache.current[id]); return }
    fetch(`/api/v1/video-pipeline/templates/${encodeURIComponent(id)}/html`, { cache: "no-store" })
      .then((r) => r.ok ? r.text() : "")
      .then((html) => { if (html) { htmlCache.current[id] = html; setTemplateHtml(html) } })
      .catch(() => {})
  }, [selected])

  // templateHtml 或 values 变化时防抖重建 srcdoc（实时预览，改参数 ~250ms 后生效）
  useEffect(() => {
    if (srcdocTimer.current) clearTimeout(srcdocTimer.current)
    srcdocTimer.current = setTimeout(() => {
      setSrcdoc(buildSrcdoc(templateHtml, values))
    }, 250)
    return () => { if (srcdocTimer.current) clearTimeout(srcdocTimer.current) }
  }, [templateHtml, values, buildSrcdoc])

  return (
    <Card className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <LayoutGrid className="h-4 w-4" />
        <h3 className="text-sm font-semibold">素材库模板（542 专业 HyperFrames 模板）</h3>
        <span className="text-xs text-muted-foreground">E:\FDE\fde-landing-delivery</span>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        浏览 542 个专业视频模板（口播演播室/标题卡/转场/数据图表/镜头…），选一个填参渲染入素材库。8 阶段编排的 compose 阶段也会自动从这里选模板。
      </p>

      {/* 过滤栏 */}
      <div className="mb-3 flex flex-wrap gap-2">
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded border border-border bg-background px-2 py-1.5 text-sm"
        >
          <option value="全部">全部分类</option>
          {categories.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2 top-2 h-4 w-4 text-muted-foreground" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜 id / 名称 / 描述…"
            className="pl-8 text-sm"
          />
        </div>
        <Button variant="outline" size="sm" onClick={() => loadTemplates()} disabled={loading}>
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "刷新"}
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 模板列表 */}
        <div className="max-h-[480px] overflow-auto rounded-lg border border-border/50 p-2">
          {templates.length === 0 ? (
            <p className="py-8 text-center text-xs text-muted-foreground">{loading ? "加载中…" : "无匹配模板"}</p>
          ) : (
            <div className="space-y-1">
              {templates.map((t) => (
                <button
                  key={t.id}
                  onClick={() => selectTemplate(t.id)}
                  className={`flex w-full flex-col rounded-lg border p-2 text-left transition hover:border-primary/40 ${selected?.id === t.id ? "border-primary bg-primary/5" : "border-border/40"}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium">{t.name}</span>
                    {t.duration && <Badge variant="outline" className="text-[9px]">{t.duration}s</Badge>}
                  </div>
                  <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-muted-foreground">
                    <span className="font-mono">{t.id}</span>
                    <span>·</span>
                    <span>{t.category}</span>
                  </div>
                  {t.description && <p className="mt-1 line-clamp-2 text-[10px] text-muted-foreground">{t.description}</p>}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* 选中模板详情 + schema 表单 + 预览 */}
        <div className="space-y-3">
          {selLoading && <p className="py-8 text-center text-xs text-muted-foreground">加载模板详情…</p>}
          {!selected && !selLoading && (
            <p className="py-8 text-center text-xs text-muted-foreground">← 点左侧模板查看详情 + 填参渲染</p>
          )}
          {selected && (
            <>
              <div className="rounded-lg border border-border/50 p-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold">{selected.name}</span>
                  <Badge variant="outline" className="text-[9px] font-mono">{selected.id}</Badge>
                </div>
                {selected.description && <p className="mt-1 text-xs text-muted-foreground">{selected.description}</p>}
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {selected.tags?.map((t) => <Badge key={t} variant="secondary" className="text-[9px]">{t}</Badge>)}
                </div>
                <div className="mt-1.5 text-[10px] text-muted-foreground">
                  {selected.duration}s · {selected.size} · {selected.schema?.length || 0} 变量
                </div>
              </div>

              {/* schema 变量表单 */}
              {selected.schema && selected.schema.length > 0 && (
                <div className="rounded-lg border border-border/50 p-3">
                  <div className="mb-2 text-xs font-medium">模板变量（改值后渲染生效）</div>
                  <div className="space-y-2">
                    {selected.schema.map((f) => (
                      <div key={f.id} className="flex items-center gap-2">
                        <label className="w-24 shrink-0 text-[11px] text-muted-foreground" title={f.id}>{f.label || f.id}</label>
                        {f.options && f.options.length > 0 ? (
                          <select
                            value={values[f.id] ?? ""}
                            onChange={(e) => setValues((v) => ({ ...v, [f.id]: e.target.value }))}
                            className="flex-1 rounded border border-border bg-background px-2 py-1 text-xs"
                          >
                            {f.options.map((o) => <option key={o.value} value={o.value}>{o.label || o.value}</option>)}
                          </select>
                        ) : (
                          <Input
                            value={values[f.id] ?? ""}
                            onChange={(e) => setValues((v) => ({ ...v, [f.id]: e.target.value }))}
                            placeholder={String(f.default ?? "")}
                            className="flex-1 text-xs"
                          />
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* 预览 + 渲染 */}
              <div className="flex items-center gap-2">
                {selected && (
                  <a href={`${LIB_PREVIEW_BASE}/templates/${encodeURIComponent(selected.id)}/index.html`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-primary">
                    <Eye className="h-3.5 w-3.5" /> 新窗口（4312）
                  </a>
                )}
                <span className="text-[10px] text-muted-foreground">实时预览（改参数即时生效，无需渲染）</span>
                <Button onClick={render} disabled={rendering} size="sm" className="ml-auto">
                  {rendering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                  <span className="ml-2">{rendering ? "渲染中…" : "渲染入素材库"}</span>
                </Button>
              </div>

              {srcdoc ? (
                <iframe
                  ref={previewRef}
                  srcDoc={srcdoc}
                  sandbox="allow-scripts allow-same-origin"
                  className="aspect-video w-full rounded-lg border border-border/50"
                  title="模板实时预览"
                />
              ) : (
                <div className="flex aspect-video w-full items-center justify-center rounded-lg border border-border/50 text-xs text-muted-foreground">
                  {selected ? "加载模板预览中…" : "← 选模板后实时预览"}
                </div>
              )}

              {renderResult && (
                <div className="rounded-lg border border-green-400/50 bg-green/5 p-2 text-xs">
                  ✅ {renderResult.outputs.join(", ")} · {renderResult.elapsed}s · file_ids={renderResult.file_ids.join(",")}{" "}
                  <a href="/materials" target="_blank" rel="noreferrer" className="ml-1 inline-flex items-center text-primary">
                    去素材库 <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </Card>
  )
}
