"use client"

import { Loader2 } from "lucide-react"

/**
 * 通用路由级加载态（App Router loading.tsx 复用）
 * 居中 Spinner + 文案；仅使用项目 border-border 语义色。
 */
export function RouteLoader({ label = "加载中..." }: { label?: string }) {
  return (
    <div className="flex min-h-[60vh] w-full flex-col items-center justify-center gap-3">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      <p className="text-sm text-muted-foreground">{label}</p>
    </div>
  )
}

export default RouteLoader
