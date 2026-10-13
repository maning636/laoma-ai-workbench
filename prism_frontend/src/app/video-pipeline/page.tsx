"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Film, Loader2, Play, Layers, ExternalLink, CheckCircle2, AlertCircle, ChevronDown, ChevronRight, Scissors, CheckSquare, Square, Plus, Sparkles, Video } from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useToast } from "@/components/ui/use-toast"
import { TemplateLibrary } from "./template-library"

interface Clip {
  name: string
  html_path: string
  thumbnail?: string | null
  has_webm: boolean
  html_excerpt: string
  html_content: string
  html_size_kb: number
  title: string | null
  description: string | null
  copy_text: string
}

interface ClipLibraryResult {
  root: string
  total_templates: number
  with_html: number
  with_webm: number
  clips: Clip[]
}

interface ConcatResult {
  ok: boolean
  clip_names: string[]
  input_count: number
  output_path: string | null
  file_id: number | null
  duration_seconds: number
  size_mb: number
  error: string | null
}

export default function VideoPipelinePage() {
  const { toast } = useToast()

  // 片段库
  const [library, setLibrary] = useState<ClipLibraryResult | null>(null)
  const [loadingLib, setLoadingLib] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)

  // 选中的片段
  const [selected, setSelected] = useState<Clip[]>([])
  const [search, setSearch] = useState("")

  // 拼接状态
  const [concatting, setConcatting] = useState(false)
  const [result, setResult] = useState<ConcatResult | null>(null)

  // 成片播放
  const [videoUrl, setVideoUrl] = useState<string | null>(null)

  const pollTimerRef = useRef<number | null>(null)

  const refreshLibrary = useCallback(async () => {
    setLoadingLib(true)
    setResult(null)
    setVideoUrl(null)
    try {
      const data = await fetch("/api/v1/fusion/video-pipeline/clips?limit=500")
      const json = await data.json()
      setLibrary(json)
    } catch (err) {
      toast({ title: "片段库加载失败", description: String(err), variant: "destructive" })
    } finally {
      setLoadingLib(false)
    }
  }, [toast])

  useEffect(() => { refreshLibrary() }, [refreshLibrary, reloadKey])
  useEffect(() => () => { if (pollTimerRef.current) window.clearInterval(pollTimerRef.current) }, [])

  const toggleSelect = (c: Clip) => {
    setSelected(prev => prev.find(x => x.name === c.name)
      ? prev.filter(x => x.name !== c.name)
      : [...prev, c])
  }

  const filtered = (library?.clips ?? []).filter(c => {
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return c.name.toLowerCase().includes(q) || c.copy_text.toLowerCase().includes(q)
  }) ?? []

  // 拼接成片：把选中的片段 HTML 拼接成完整片，走 compose 渲染
  const doConcat = async () => {
    if (selected.length === 0) {
      toast({ title: "请至少选 1 个片段", variant: "destructive" })
      return
    }
    setConcatting(true)
    setResult(null)
    setVideoUrl(null)
    try {
      const res = await fetch("/api/v1/fusion/video-pipeline/concat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          clip_names: selected.map(c => c.name),
          output_name: "剪辑_" + new Date().toISOString().slice(0,10) + "_" + selected.length + "片段",
        }),
      })
      const json = await res.json()
      setResult(json)
      if (json.ok && json.output_path) {
        // 生成播放 URL
        const absPath = json.output_path.replace(/\\/g, "/")
        // 用临时 HTTP 服务或本地文件协议
        // 走后端 asset 接口预览（如果已上传素材库）
        if (json.file_id) {
          // 通过 assets 接口拿到 url
          fetch(`/api/v1/assets/${json.file_id}`).then(r=>r.ok?r.json():null).then(d => {
            if (d?.url) setVideoUrl(d.url)
          }).catch(() => {})
        }
        toast({ title: "剪辑完成", description: `${json.duration_seconds}s / ${json.size_mb}MB，已入素材库` })
      } else {
        toast({ title: "剪辑失败", description: json.error || "未知错误", variant: "destructive" })
      }
    } catch (err) {
      toast({ title: "剪辑失败", description: String(err), variant: "destructive" })
    } finally {
      setConcatting(false)
    }
  }

  const clearSelection = () => { setSelected([]); setResult(null); setVideoUrl(null) }

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-border bg-background/80 backdrop-blur-xl sticky top-0 z-50">
        <div>
          <PageHeader title="视频剪辑" description="从 4312 片段库挑片段，剪成完整视频，直接推素材库发布" />
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" onClick={() => setReloadKey(k => k+1)} disabled={loadingLib}>
            <Film className="h-3 w-3 mr-1.5" /> {loadingLib ? "刷新中" : "刷新片段库"}
          </Button>
          {selected.length > 0 && (
            <Button variant="outline" size="sm" onClick={clearSelection}>
              清空
            </Button>
          )}
          <Button size="sm" onClick={doConcat} disabled={concatting || selected.length === 0}>
            {concatting ? <Loader2 className="h-3.5 w-3.5 animate-spin mr-1.5" /> : <Scissors className="h-3.5 w-3.5 mr-1.5" />}
            {concatting ? "剪辑中..." : `拼接成片（${selected.length} 片段）`}
          </Button>
        </div>
      </div>

      {/* 主体：左片段库 + 右剪辑台 */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* 左：片段库 */}
        <div className="w-80 border-r border-border flex flex-col flex-shrink-0">
          <div className="p-3 border-b border-border">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium">片段库</div>
              <div className="text-xs text-muted-foreground">{filtered.length} / {library?.total_templates ?? "-"}</div>
            </div>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索片段名或文案..."
              className="h-8 w-full px-3 text-xs rounded-md border border-border bg-background/50 focus:outline-none focus:border-primary"
            />
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-2">
            {loadingLib && <div className="text-center text-xs text-muted-foreground py-8">加载中...</div>}
            {filtered.length === 0 && !loadingLib && (
              <div className="text-center text-xs text-muted-foreground py-8">无匹配片段</div>
            )}
            {filtered.map(c => {
              const isSel = selected.some(x => x.name === c.name)
              return (
                <div
                  key={c.name}
                  onClick={() => toggleSelect(c)}
                  className={`cursor-pointer rounded-lg border p-2.5 transition-all ${
                    isSel ? "border-primary bg-primary/5 ring-1 ring-primary/20" : "border-border hover:border-primary/40 hover:bg-accent/30"
                  }`}
                >
                  <div className="flex items-start gap-2">
                    <div className={`mt-0.5 flex-shrink-0 ${isSel ? "text-primary" : "text-muted-foreground"}`}>
                      {isSel ? <CheckSquare className="h-3.5 w-3.5" /> : <Square className="h-3.5 w-3.5" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-mono font-medium truncate" title={c.name}>{c.name}</div>
                      <div className="text-[10px] text-muted-foreground truncate mt-0.5">
                        {c.copy_text.slice(0, 40)}{c.copy_text.length > 40 ? "..." : ""}
                      </div>
                      <div className="flex items-center gap-1.5 mt-1.5 text-[10px] text-muted-foreground">
                        {c.has_webm && <Badge variant="outline" className="h-4 px-1.5 text-[9px]">6-8s</Badge>}
                        <span>{c.html_size_kb}KB HTML</span>
                        {c.title && <span className="text-primary/70">· 有标题</span>}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        {/* 右：剪辑台 */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* 片段队列 */}
          <div className="border-b border-border px-4 py-3 bg-background/50">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <Scissors className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium">剪辑队列</span>
                <span className="text-xs text-muted-foreground">（点击左侧片段添加，可多选后一次拼接）</span>
              </div>
              <span className="text-xs text-muted-foreground">{selected.length} 个片段</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {selected.length === 0 && (
                <div className="text-xs text-muted-foreground py-2">还没选片段。点左侧片段加进来，然后点「拼接成片」剪成完整视频。</div>
              )}
              {selected.map((c, i) => (
                <div key={c.name} className="flex items-center gap-1.5 px-2 py-1 rounded bg-primary/10 border border-primary/30 text-xs">
                  <span className="text-primary font-mono">#{i+1}</span>
                  <span className="font-mono text-foreground">{c.name}</span>
                  <button onClick={() => toggleSelect(c)} className="text-muted-foreground hover:text-destructive text-[10px]">✕</button>
                </div>
              ))}
            </div>
          </div>

          {/* 成片预览 + 结果 */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {result?.ok && videoUrl ? (
              <>
                <Card className="p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                    <div className="font-semibold">剪辑完成</div>
                    <Badge variant="outline" className="ml-auto">{result.duration_seconds}s</Badge>
                    <Badge variant="outline">{result.size_mb}MB</Badge>
                  </div>
                  <div className="flex items-center gap-1.5 mb-3 flex-wrap">
                    {result.clip_names.map((n, i) => (
                      <span key={i} className="text-xs px-2 py-1 bg-primary/10 rounded font-mono">{n}</span>
                    ))}
                  </div>
                  <video
                    src={videoUrl}
                    controls
                    className="w-full max-h-96 bg-popover rounded-lg"
                  />
                  {result.file_id && (
                    <div className="mt-3 text-xs text-emerald-600 flex items-center gap-1.5">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      已入素材库 · ID {result.file_id}，可直接走矩阵发布
                    </div>
                  )}
                  <div className="mt-3 flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => { window.open(videoUrl, "_blank") }}>
                      <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> 新窗口打开
                    </Button>
                    {result.file_id && (
                      <Button size="sm" onClick={() => {
                        window.dispatchEvent(new CustomEvent("navigate", { detail: { path: `/files?tag=剪辑_${result.file_id}` } }))
                      }}>
                        <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> 去素材库发布
                      </Button>
                    )}
                  </div>
                </Card>
                <Card className="p-3">
                  <div className="text-xs font-mono text-muted-foreground break-all">
                    {result.output_path}
                  </div>
                </Card>
              </>
            ) : result?.ok ? (
              <Card className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                  <div className="font-semibold">剪辑完成 · {result.duration_seconds}s / {result.size_mb}MB</div>
                </div>
                <div className="text-xs text-muted-foreground">视频文件已生成（{result.clip_names.length} 片段拼接），但预览 URL 暂未就绪。</div>
                <div className="mt-2 text-xs font-mono text-muted-foreground break-all">{result.output_path}</div>
              </Card>
            ) : concatting ? (
              <Card className="p-8 text-center">
                <Loader2 className="h-10 w-10 animate-spin text-primary mx-auto mb-3" />
                <div className="font-medium mb-1">正在剪辑 {selected.length} 个片段...</div>
                <div className="text-sm text-muted-foreground">拼接 HTML → 渲染成片 → 上传素材库，约 1-2 分钟</div>
              </Card>
            ) : (
              <Card className="p-8 text-center text-muted-foreground">
                <Video className="h-12 w-12 mx-auto mb-3 text-muted-foreground/30" />
                <div className="font-medium text-foreground mb-1">从左侧片段库挑选片段</div>
                <div className="text-sm">选 2-5 个片段 → 点「拼接成片」→ 自动剪成完整视频并推素材库</div>
                <div className="mt-4 grid grid-cols-3 gap-3 text-xs">
                  <div className="p-3 rounded-lg bg-muted/30">
                    <div className="font-medium text-foreground mb-1">1. 选片段</div>
                    <div>从 4312 片段库多选</div>
                  </div>
                  <div className="p-3 rounded-lg bg-muted/30">
                    <div className="font-medium text-foreground mb-1">2. 拼接</div>
                    <div>自动拼接成完整视频</div>
                  </div>
                  <div className="p-3 rounded-lg bg-muted/30">
                    <div className="font-medium text-foreground mb-1">3. 发布</div>
                    <div>入素材库，走矩阵发布</div>
                  </div>
                </div>
              </Card>
            )}

            {!result?.ok && !concatting && (
              <Card className="p-4">
                <div className="flex items-center gap-2 mb-3">
                  <Sparkles className="h-4 w-4 text-primary" />
                  <div className="font-medium">片段聚合</div>
                </div>
                {selected.length === 0 ? (
                  <div className="text-xs text-muted-foreground">选了片段后这里会聚合标题/描述/文案。</div>
                ) : (
                  <div className="space-y-2">
                    {selected.map((c, i) => (
                      <div key={i} className="p-2.5 rounded-md bg-muted/30 border border-border">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-mono font-medium text-primary">#{i+1}</span>
                          <span className="text-xs font-mono">{c.name}</span>
                        </div>
                        <div className="text-xs text-muted-foreground leading-relaxed">{c.copy_text.slice(0, 100)}</div>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
