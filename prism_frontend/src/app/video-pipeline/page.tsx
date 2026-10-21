"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Film, Loader2, Play, Layers, ExternalLink, CheckCircle2, AlertCircle, ChevronDown, ChevronRight, Scissors, CheckSquare, Square, Plus, Sparkles, Video } from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useToast } from "@/components/ui/use-toast"

interface Clip {
  id: string
  name: string
  description: string
  category: string
  tags: string[]
  duration?: number
  size?: string
  dir?: string
}

interface ClipLibraryResult {
  count: number
  total: number
  categories: string[]
  clips: Clip[]
}

interface ConcatResult {
  ok: boolean
  outputs: string[]
  file_ids: number[]
  elapsed_seconds: number
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
      // 后端真实端点：GET /api/v1/video-pipeline/templates（素材库 HyperFrames 模板）
      const res = await fetch("/api/v1/video-pipeline/templates", { cache: "no-store" })
      const json = await res.json()
      if (!res.ok || json?.status !== "success") {
        throw new Error(json?.detail || `加载模板失败 (${res.status})`)
      }
      const r = json.result ?? {}
      setLibrary({
        count: r.count ?? 0,
        total: r.total ?? 0,
        categories: r.categories ?? [],
        clips: r.templates ?? [],
      })
    } catch (err) {
      toast({ title: "片段库加载失败", description: String(err), variant: "destructive" })
    } finally {
      setLoadingLib(false)
    }
  }, [toast])

  useEffect(() => { refreshLibrary() }, [refreshLibrary, reloadKey])
  useEffect(() => () => { if (pollTimerRef.current) window.clearInterval(pollTimerRef.current) }, [])

  const toggleSelect = (c: Clip) => {
    setSelected(prev => prev.find(x => x.id === c.id)
      ? prev.filter(x => x.id !== c.id)
      : [...prev, c])
  }

  const filtered = (library?.clips ?? []).filter(c => {
    if (!search.trim()) return true
    const q = search.toLowerCase()
    return c.name.toLowerCase().includes(q) || c.description.toLowerCase().includes(q)
  }) ?? []

  // 渲染成片：把选中的模板逐个走 /api/v1/video-pipeline/render（HyperFrames → MP4 → 自动入素材库）
  const doConcat = async () => {
    if (selected.length === 0) {
      toast({ title: "请至少选 1 个片段", variant: "destructive" })
      return
    }
    setConcatting(true)
    setResult(null)
    setVideoUrl(null)
    try {
      const outputs: string[] = []
      const fileIds: number[] = []
      let elapsed = 0
      for (const c of selected) {
        const detailRes = await fetch(`/api/v1/video-pipeline/templates/${encodeURIComponent(c.id)}`, {
          cache: "no-store",
        })
        const detail = await detailRes.json().catch(() => ({}))
        const dir = detail?.result?.dir
        if (!detailRes.ok || !dir) {
          throw new Error(`模板「${c.name}」缺少可渲染目录`)
        }

        const form = new FormData()
        form.append("composition_dir", dir)
        form.append("quality", "standard")
        form.append("fps", "30")

        const res = await fetch("/api/v1/video-pipeline/render", { method: "POST", body: form })
        const json = await res.json()
        if (!res.ok || json?.status !== "success") {
          throw new Error(json?.detail || `渲染「${c.name}」失败 (${res.status})`)
        }
        outputs.push(...(json.result.outputs ?? []))
        fileIds.push(...(json.result.file_ids ?? []))
        elapsed += json.result.elapsed_seconds ?? 0
      }

      setResult({ ok: true, outputs, file_ids: fileIds, elapsed_seconds: elapsed, error: null })

      // 渲染产物已自动入素材库，取详情拿到可播放地址
      const firstFileId = fileIds[0]
      if (firstFileId) {
        const fileRes = await fetch(`/api/v1/files/${firstFileId}`, { cache: "no-store" })
        const fileData = await fileRes.json().catch(() => ({}))
        const url = fileData?.file_url || fileData?.url || fileData?.file_path
        if (url) setVideoUrl(url)
      }

      toast({
        title: "渲染完成",
        description: `${outputs.length} 个产物，已入素材库（file_ids: ${fileIds.join(", ") || "无"}）`,
      })
    } catch (err) {
      setResult({ ok: false, outputs: [], file_ids: [], elapsed_seconds: 0, error: String(err) })
      toast({ title: "渲染失败", description: String(err), variant: "destructive" })
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
          <PageHeader title="视频流水线" description="从 HyperFrames 模板库挑片段渲染成片，产物自动入素材库可直接发布" />
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
              <div className="text-xs text-muted-foreground">{filtered.length} / {library?.total ?? "-"}</div>
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
              const isSel = selected.some(x => x.id === c.id)
              return (
                <div
                  key={c.id}
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
                        {c.description.slice(0, 40)}{c.description.length > 40 ? "..." : ""}
                      </div>
                      <div className="flex items-center gap-1.5 mt-1.5 text-[10px] text-muted-foreground">
                        {c.duration ? <Badge variant="outline" className="h-4 px-1.5 text-[9px]">{c.duration}s</Badge> : null}
                        {c.category && <Badge variant="secondary" className="h-4 px-1.5 text-[9px]">{c.category}</Badge>}
                        {c.size && <span>{c.size}</span>}
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
                <div key={c.id} className="flex items-center gap-1.5 px-2 py-1 rounded bg-primary/10 border border-primary/30 text-xs">
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
                    <div className="font-semibold">渲染完成</div>
                    <Badge variant="outline" className="ml-auto">{result.elapsed_seconds}s</Badge>
                    <Badge variant="outline">{result.outputs.length} 个产物</Badge>
                  </div>
                  <div className="flex items-center gap-1.5 mb-3 flex-wrap">
                    {result.outputs.map((n, i) => (
                      <span key={i} className="text-xs px-2 py-1 bg-primary/10 rounded font-mono">{n}</span>
                    ))}
                  </div>
                  <video
                    src={videoUrl}
                    controls
                    className="w-full max-h-96 bg-popover rounded-lg"
                  />
                  {result.file_ids.length > 0 && (
                    <div className="mt-3 text-xs text-emerald-600 flex items-center gap-1.5">
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      已入素材库 · ID {result.file_ids.join(", ")}，可直接走矩阵发布
                    </div>
                  )}
                  <div className="mt-3 flex gap-2">
                    <Button variant="outline" size="sm" onClick={() => { window.open(videoUrl, "_blank") }}>
                      <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> 新窗口打开
                    </Button>
                    {result.file_ids.length > 0 && (
                      <Button size="sm" onClick={() => {
                        window.dispatchEvent(new CustomEvent("navigate", { detail: { path: `/files?tag=video-pipeline` } }))
                      }}>
                        <ExternalLink className="h-3.5 w-3.5 mr-1.5" /> 去素材库发布
                      </Button>
                    )}
                  </div>
                </Card>
              </>
            ) : result?.ok ? (
              <Card className="p-4">
                <div className="flex items-center gap-2 mb-2">
                  <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                  <div className="font-semibold">渲染完成 · {result.elapsed_seconds}s · {result.outputs.length} 个产物</div>
                </div>
                <div className="text-xs text-muted-foreground">视频文件已生成，但预览 URL 暂未就绪。</div>
                <div className="mt-2 text-xs font-mono text-muted-foreground break-all">{result.outputs.join(", ")}</div>
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
                    <div>从模板库多选</div>
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
                        <div className="text-xs text-muted-foreground leading-relaxed">{c.description.slice(0, 100)}</div>
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
