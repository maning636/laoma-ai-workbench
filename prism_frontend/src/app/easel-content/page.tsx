"use client"

import { useCallback, useEffect, useState } from "react"
import {
  ExternalLink,
  Eye,
  FileText,
  Film,
  FolderOpen,
  Image as ImageIcon,
  Loader2,
  Music,
  RefreshCw,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

interface OutputNode {
  name: string
  type: "dir" | "file"
  path: string
  kind?: string
  mtime: number
  size?: number
  fileCount?: number
  children?: OutputNode[]
  meta?: {
    title?: string
    summary?: string
    platform?: string
    kind?: string
    status?: string
    tags?: string[]
    cover?: string
    deliverablePaths?: string[]
  }
}

function mediaUrl(path: string) {
  return `/api/v1/content-library/media?path=${encodeURIComponent(path)}`
}

function fmtTime(mtime: number) {
  if (!mtime) return ""
  return new Date(mtime * 1000).toLocaleString("zh-CN", { hour12: false })
}

function flattenFiles(node: OutputNode, out: OutputNode[] = []): OutputNode[] {
  if (node.type === "file") {
    out.push(node)
    return out
  }
  for (const c of node.children || []) flattenFiles(c, out)
  return out
}

function fileIcon(kind?: string) {
  if (kind === "image") return <ImageIcon className="h-4 w-4" />
  if (kind === "video") return <Film className="h-4 w-4" />
  if (kind === "audio") return <Music className="h-4 w-4" />
  return <FileText className="h-4 w-4" />
}

export default function ContentLibraryPage() {
  const [catalog, setCatalog] = useState<{ total: number; total_files: number; items: OutputNode[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<OutputNode | null>(null)
  const [preview, setPreview] = useState<{ url: string; kind: string; name: string } | null>(null)
  const [textContent, setTextContent] = useState<{ name: string; content: string } | null>(null)

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

  useEffect(() => {
    void load()
  }, [load])

  const openText = async (f: OutputNode) => {
    const res = await fetch(`/api/v1/content-library/file?path=${encodeURIComponent(f.path)}`)
    const data = await res.json()
    setTextContent({ name: f.name, content: data?.result?.content || "" })
  }

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · CONTENT LIBRARY"
        title="内容库"
        description="创作产物全量浏览（磁盘直读）：项目、元数据与成品文件预览。"
        actions={
          <Button variant="ghost" onClick={load} disabled={loading}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
            刷新
          </Button>
        }
      />

      <div className="mx-auto max-w-7xl space-y-5 px-6 py-6">
        {loading ? (
          <Card className="p-10 text-center text-muted-foreground">
            <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2" /> 正在扫描内容库…
          </Card>
        ) : !catalog || catalog.total === 0 ? (
          <Card className="p-10 text-center text-sm text-muted-foreground">内容库为空。完成创作后产物会出现在这里。</Card>
        ) : (
          <div className="grid gap-5 lg:grid-cols-[380px_1fr]">
            <div className="space-y-3 lg:max-h-[75vh] lg:overflow-y-auto lg:pr-1">
              {catalog.items.map((node) => {
                const active = selected?.path === node.path
                const cover = node.meta?.cover
                return (
                  <Card
                    key={node.path}
                    className={`cursor-pointer overflow-hidden transition ${active ? "border-primary" : "hover:border-primary/40"}`}
                    onClick={() => setSelected(node)}
                  >
                    <div className="flex gap-3 p-3">
                      <div className="h-16 w-16 shrink-0 overflow-hidden rounded-lg bg-muted">
                        {cover ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={mediaUrl(cover)} alt="" className="h-full w-full object-cover" loading="lazy" />
                        ) : (
                          <div className="flex h-full items-center justify-center text-muted-foreground">
                            <FolderOpen className="h-5 w-5" />
                          </div>
                        )}
                      </div>
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="truncate text-sm font-medium">{node.meta?.title || node.name}</div>
                        <div className="flex flex-wrap items-center gap-1">
                          {node.meta?.platform && <Badge variant="outline" className="text-xs">{node.meta.platform}</Badge>}
                          <span className="text-xs text-muted-foreground">{node.fileCount} 文件 · {fmtTime(node.mtime)}</span>
                        </div>
                      </div>
                    </div>
                  </Card>
                )
              })}
            </div>

            <div>
              {selected ? (
                <Card className="p-5">
                  <div className="mb-4 space-y-2">
                    <h2 className="text-lg font-semibold">{selected.meta?.title || selected.name}</h2>
                    {selected.meta?.summary && (
                      <p className="text-sm text-muted-foreground">{selected.meta.summary}</p>
                    )}
                    <div className="flex flex-wrap items-center gap-1.5">
                      {selected.meta?.platform && <Badge variant="outline">{selected.meta.platform}</Badge>}
                      {selected.meta?.status && <Badge variant="secondary">{selected.meta.status}</Badge>}
                      {(selected.meta?.tags || []).map((t) => (
                        <Badge key={t} variant="outline">#{t}</Badge>
                      ))}
                      <span className="text-xs text-muted-foreground">更新于 {fmtTime(selected.mtime)}</span>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {flattenFiles(selected).map((f) => (
                      <div key={f.path} className="flex items-center justify-between gap-2 rounded-lg border p-2.5">
                        <div className="flex min-w-0 items-center gap-2 text-sm">
                          <span className="text-muted-foreground">{fileIcon(f.kind)}</span>
                          <span className="truncate">{f.name}</span>
                          {f.size ? <span className="shrink-0 text-xs text-muted-foreground">{(f.size / 1024).toFixed(0)} KB</span> : null}
                        </div>
                        <div className="flex shrink-0 items-center gap-1">
                          {f.kind === "text" && (
                            <Button size="sm" variant="ghost" onClick={() => openText(f)}>
                              <FileText className="h-4 w-4" />
                            </Button>
                          )}
                          {(f.kind === "image" || f.kind === "video" || f.kind === "audio") && (
                            <Button size="sm" variant="ghost" onClick={() => setPreview({ url: mediaUrl(f.path), kind: f.kind || "", name: f.name })}>
                              <Eye className="h-4 w-4" />
                            </Button>
                          )}
                          <a href={mediaUrl(f.path)} target="_blank" rel="noreferrer">
                            <Button size="sm" variant="ghost">
                              <ExternalLink className="h-4 w-4" />
                            </Button>
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              ) : (
                <Card className="grid h-full place-items-center p-10 text-sm text-muted-foreground">
                  左侧选择一个项目查看文件与预览
                </Card>
              )}
            </div>
          </div>
        )}
      </div>

      {preview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-6" onClick={() => setPreview(null)}>
          <div className="max-h-[90vh] max-w-5xl overflow-auto" onClick={(e) => e.stopPropagation()}>
            {preview.kind === "image" ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview.url} alt={preview.name} className="max-h-[85vh] max-w-full object-contain" />
            ) : preview.kind === "video" ? (
              <video src={preview.url} controls autoPlay className="max-h-[85vh] max-w-full" />
            ) : (
              <audio src={preview.url} controls autoPlay className="w-96" />
            )}
            <div className="mt-2 text-center text-sm text-white/80">{preview.name}（点击空白关闭）</div>
          </div>
        </div>
      )}

      {textContent && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6" onClick={() => setTextContent(null)}>
          <div className="max-h-[85vh] w-full max-w-3xl overflow-auto rounded-xl bg-card p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
            <div className="mb-3 text-sm font-semibold">{textContent.name}</div>
            <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed">{textContent.content}</pre>
          </div>
        </div>
      )}
    </div>
  )
}
