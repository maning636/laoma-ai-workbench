"use client"

import { useEffect, useState } from "react"
import { useRouter } from "next/navigation"
import {
  Database, Palette, Shield, Boxes, BarChart3,
  Settings, Activity, ChevronRight, Loader2, CheckCircle2, AlertCircle,
} from "lucide-react"
import { PageHeader } from "@/components/layout/page-scaffold"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { API_ENDPOINTS } from "@/lib/env"

// 注：创作/热点/技能/认知/生图类能力已由 Easel 工作台承担（/easel 与 /easel-inbox），
// 这里只保留 老马AI工作台 自有的运营向能力。后端 /api/v1/fusion/* 接口保留（发布链路依赖）。
const MODULES = [
  {
    id: "providers",
    path: "/fusion/providers",
    title: "AI 多 Provider 注册表",
    description: "11+ 主流 LLM 供应商统一管理，自动探测 API Key",
    icon: Database,
    tag: "P0",
    priority: "核心能力",
  },
  {
    id: "styles",
    path: "/fusion/styles",
    title: "平台差异化风格",
    description: "7+ 平台语气、结构、emoji、封面规则，支持前台 CRUD",
    icon: Palette,
    tag: "P0",
    priority: "核心能力",
  },
  {
    id: "moderation",
    path: "/fusion/moderation",
    title: "三层内容审核",
    description: "敏感词本地检测 → Qwen 语义审核 → AI 合规改写",
    icon: Shield,
    tag: "P0",
    priority: "核心能力",
  },
  {
    id: "model-market",
    path: "/fusion/model-market",
    title: "模型广场",
    description: "11+ LLM 能力对比、价格、能力标签、API Key 状态",
    icon: Boxes,
    tag: "P1",
    priority: "增强",
  },
  {
    id: "analytics",
    path: "/fusion/analytics",
    title: "NL→SQL 数据分析",
    description: "自然语言提问 → SQL → 图表 + 洞察",
    icon: BarChart3,
    tag: "P1",
    priority: "增强",
  },
  {
    id: "config",
    path: "/fusion/config",
    title: "前台配置中心",
    description: "敏感词 / 平台风格 / 预设问题 等 20+ 组配置 CRUD",
    icon: Settings,
    tag: "P1",
    priority: "增强",
  },
]

export default function FusionHome() {
  const router = useRouter()
  const [health, setHealth] = useState<null | { status: string; modules: string[] }>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    const base = API_ENDPOINTS.base
    fetch(`${base}/api/v1/fusion/health`)
      .then((r) => r.json())
      .then((d) => setHealth(d))
      .catch(() => setHealth({ status: "error", modules: [] }))
      .finally(() => setChecking(false))
  }, [])

  return (
    <div className="min-h-screen">
      <PageHeader
        title="AI 能力扩展"
        description="老马AI研习社自有的运营向扩展能力。内容创作 / 热点发现由 AI 工作台承担。"
      />
      <div className="mx-auto max-w-6xl space-y-6 px-6 pb-12">
        <Card className="p-5">
          <div className="flex items-center gap-3">
            <Activity className="h-5 w-5 text-muted-foreground" />
            <span className="font-medium">后端服务状态</span>
            {checking && <Loader2 className="h-4 w-4 animate-spin" />}
            {!checking && health?.status === "ok" && (
              <span className="flex items-center gap-1 text-green-600">
                <CheckCircle2 className="h-4 w-4" />
                <span className="text-sm">已连接 · {health.modules.length} 个模块就绪</span>
              </span>
            )}
            {!checking && health?.status !== "ok" && (
              <span className="flex items-center gap-1 text-orange-600">
                <AlertCircle className="h-4 w-4" />
                <span className="text-sm">后端未连接（启动 prism_backend 后重试）</span>
              </span>
            )}
          </div>
        </Card>

        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m) => {
            const Icon = m.icon
            const isP0 = m.tag === "P0"
            return (
              <Card
                key={m.id}
                className="cursor-pointer p-5 transition-all hover:shadow-md hover:border-primary/40"
                onClick={() => router.push(m.path)}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <div className="rounded-lg bg-primary/10 p-2">
                      <Icon className="h-5 w-5 text-primary" />
                    </div>
                    <Badge variant={isP0 ? "default" : "secondary"}>
                      {m.tag}
                    </Badge>
                  </div>
                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                </div>
                <h3 className="text-base font-semibold mb-1">{m.title}</h3>
                <p className="text-xs text-muted-foreground leading-relaxed">{m.description}</p>
                <div className="mt-3 text-xs text-muted-foreground">
                  <span className="font-medium">优先级：</span>{m.priority}
                </div>
              </Card>
            )
          })}
        </div>

        <Card className="p-5 bg-muted/40">
          <div className="text-sm text-muted-foreground space-y-1">
            <div className="font-medium text-foreground">技术说明</div>
            <div>· 后端代码位于 <code className="bg-background px-1.5 py-0.5 rounded">prism_backend/fusion_ai/</code>，独立于原生 ai_service</div>
            <div>· 通过 <code className="bg-background px-1.5 py-0.5 rounded">/api/v1/fusion/*</code> 统一暴露，不修改任何原生路由</div>
            <div>· 数据持久化使用 <code className="bg-background px-1.5 py-0.5 rounded">$DATA_DIR</code>，默认 <code className="bg-background px-1.5 py-0.5 rounded">prism_backend/data/</code>，可通过环境变量覆盖</div>
          </div>
        </Card>
      </div>
    </div>
  )
}