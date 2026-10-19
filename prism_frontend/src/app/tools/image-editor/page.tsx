"use client"

import { Suspense, useMemo } from "react"
import { useSearchParams } from "next/navigation"
import { ImageEditor } from "@/components/image-editor/image-editor"
import { PageHeader } from "@/components/layout/page-scaffold"

// `export const metadata` 必须放在 server component；本页用 useSearchParams 读 query，
// 因此拆成外层（server）+ 内层（client）以支持 /tools/image-editor?url=<imgUrl>。

function ImageEditorPageInner() {
  const searchParams = useSearchParams()
  const initialUrl = useMemo(() => {
    const v = searchParams.get("url")
    if (!v) return undefined
    // 只允许 http(s) URL，避免误把相对路径塞进 fetch
    try {
      const u = new URL(v)
      if (u.protocol === "http:" || u.protocol === "https:") return u.toString()
    } catch {
      /* ignore */
    }
    return undefined
  }, [searchParams])

  return (
    <div className="space-y-4 p-6">
      <PageHeader
        title="图片编辑器"
        eyebrow="M5 · 图片编辑器"
        description="react-image-crop + fabric.js · 上传 → 裁剪 → 编辑 → 导出（PNG/JPG）"
      />
      <ImageEditor initialUrl={initialUrl} />
    </div>
  )
}

export default function ImageEditorPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">加载中…</div>}>
      <ImageEditorPageInner />
    </Suspense>
  )
}
