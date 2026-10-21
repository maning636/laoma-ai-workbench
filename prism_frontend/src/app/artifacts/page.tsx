"use client"

// 产物中心 · 统一产物总线
// 风格对齐 review/page.tsx 与 tasks/publish/page.tsx：
//   - React Query 管理请求状态
//   - shadcn/ui 组件从 @/components/ui/* 导入
//   - Tailwind 语义化 class，禁止硬编码 bg-white / text-black
//   - 中文界面 + 中文注释
//
// 这个页面的意义：把「AI 生图 / 素材上传 / 视频渲染」的产出统一成一类「产物」，
// 每条都有唯一 artifact_id（art_xxx），可以推进阶段（送审 → 通过 → 发布），
// 也可以查血缘（谁派生了谁）。功能之间的串联在这里是可见的。

import { useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  Boxes,
  ChevronRight,
  GitBranch,
  Image as ImageIcon,
  Loader2,
  RefreshCcw,
  Search,
  Send,
  Video,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useToast } from "@/components/ui/use-toast"
import { backendBaseUrl } from "@/lib/env"

// ============ 类型定义 ============

/** 产物阶段（与后端 prism_core/artifacts.py 的 STAGE_* 对齐） */
type ArtifactStage =
  | "generated"
  | "uploaded"
  | "reviewing"
  | "approved"
  | "rejected"
  | "published"

/** 产物（后端 artifacts 表行） */
interface Artifact {
  artifact_id: string
  stage: ArtifactStage | string
  kind?: string
  title?: string
  path?: string
  thumb?: string
  media_type?: string
  source?: string
  ref_type?: string
  ref_id?: string
  parent_id?: string | null
  campaign_id?: string
  platform?: string
  review_id?: string
  publish_task_id?: string
  meta?: Record<string, unknown>
  created_at?: string
  updated_at?: string
}

/** 产物列表响应 */
interface ArtifactListResponse {
  total: number
  items: Artifact[]
}

/** 产物统计 */
interface ArtifactStats {
  total: number
  by_stage: Record<string, number>
  by_source: Record<string, number>
  by_kind: Record<string, number>
}

/** 血缘 */
interface ArtifactLineage {
  artifact_id: string
  parent: Artifact | null
  ancestors: Artifact[]
  children: Artifact[]
}

// ============ 展示映射 ============

type BadgeVariant = "default" | "secondary" | "outline" | "destructive" | "accent"

const STAGE_META: Record<string, { label: string; variant: BadgeVariant }> = {
  generated: { label: "已生成", variant: "secondary" },
  uploaded: { label: "已上传", variant: "secondary" },
  reviewing: { label: "审核中", variant: "default" },
  approved: { label: "已通过", variant: "outline" },
  rejected: { label: "已拒绝", variant: "destructive" },
  published: { label: "已发布", variant: "outline" },
}

const SOURCE_META: Record<string, string> = {
  image_gen: "AI 生图",
  upload: "素材上传",
  video_pipeline: "视频流水线",
  manual: "手动登记",
  workshop: "创作工坊",
}

const KIND_META: Record<string, string> = {
  image: "图片",
  video: "视频",
  audio: "音频",
  text: "文本",
  file: "文件",
  other: "其他",
}

const STAGE_ORDER: ArtifactStage[] = [
  "generated",
  "uploaded",
  "reviewing",
  "approved",
  "rejected",
  "published",
]

// ============ 工具函数 ============

function formatDate(input?: string): string {
  if (!input) return "-"
  const d = new Date(input)
  if (Number.isNaN(d.getTime())) return input
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/** 产物预览地址：远程 URL / data URL 直用，本地路径走 /getFile 代理。 */
function previewUrl(a: Artifact): string {
  const p = a.thumb || a.path || ""
  if (!p) return ""
  if (p.startsWith("http") || p.startsWith("data:")) return p
  return `${backendBaseUrl}/getFile?filename=${encodeURIComponent(p)}`
}

function isPreviewable(a: Artifact): boolean {
  const k = (a.kind || "").toLowerCase()
  return k === "image" || k === "video"
}

// ============ 页面 ============

export default function ArtifactsPage() {
  const { toast } = useToast()

  // 过滤器
  const [stage, setStage] = useState<string>("all")
  const [source, setSource] = useState<string>("all")
  const [kind, setKind] = useState<string>("all")
  const [keyword, setKeyword] = useState<string>("")
  const [appliedKeyword, setAppliedKeyword] = useState<string>("")

  // 详情弹窗
  const [detail, setDetail] = useState<Artifact | null>(null)

  const params = useMemo(() => {
    const p = new URLSearchParams({ limit: "200" })
    if (stage !== "all") p.set("stage", stage)
    if (source !== "all") p.set("source", source)
    if (kind !== "all") p.set("kind", kind)
    if (appliedKeyword) p.set("keyword", appliedKeyword)
    return p.toString()
  }, [stage, source, kind, appliedKeyword])

  const {
    data: listData,
    isLoading,
    refetch: refetchList,
  } = useQuery({
    queryKey: ["artifacts", params],
    queryFn: async () => {
      const res = await fetch(`/api/v1/artifacts?${params}`)
      if (!res.ok) throw new Error(`产物加载失败 (HTTP ${res.status})`)
      const json = (await res.json()) as ArtifactListResponse
      return json
    },
  })

  const {
    data: statsData,
    refetch: refetchStats,
  } = useQuery({
    queryKey: ["artifacts-stats"],
    queryFn: async () => {
      const res = await fetch("/api/v1/artifacts/stats")
      if (!res.ok) throw new Error(`统计加载失败 (HTTP ${res.status})`)
      return (await res.json()) as ArtifactStats
    },
  })

  const {
    data: lineageData,
    refetch: refetchLineage,
  } = useQuery({
    queryKey: ["artifact-lineage", detail?.artifact_id],
    queryFn: async () => {
      if (!detail?.artifact_id) return null
      const res = await fetch(`/api/v1/artifacts/${detail.artifact_id}/lineage`)
      if (!res.ok) throw new Error(`血缘加载失败 (HTTP ${res.status})`)
      return (await res.json()) as ArtifactLineage
    },
    enabled: !!detail?.artifact_id,
  })

  // 送审：把产物推进到审核中，并自动入审核队列
  const submitReview = useMutation({
    mutationFn: async (artifactId: string) => {
      const res = await fetch(`/api/v1/artifacts/${artifactId}/submit-review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: "产物送审",
          content: "来自产物中心的送审请求",
        }),
      })
      if (!res.ok) {
        const detailText = await res.text()
        throw new Error(`送审失败 (HTTP ${res.status}) ${detailText.slice(0, 200)}`)
      }
      return (await res.json()) as { artifact_id: string; review_id: string }
    },
    onSuccess: (data) => {
      toast({
        title: "已送审",
        description: `审核项 ${data.review_id.slice(0, 12)}… · 阶段已推进到「审核中」`,
      })
      void refetchList()
      void refetchStats()
      if (detail?.artifact_id === data.artifact_id) {
        void refetchLineage()
      }
    },
    onError: (err) => {
      toast({ variant: "destructive", title: "送审失败", description: String(err) })
    },
  })

  const items = listData?.items ?? []
  const stats = statsData

  const handleRefresh = () => {
    void refetchList()
    void refetchStats()
    toast({ title: "已刷新" })
  }

  const handleSearch = () => {
    setAppliedKeyword(keyword.trim())
  }

  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 py-4">
      <PageHeader
        eyebrow="ARTIFACTS · 统一产物总线"
        title="产物中心"
        description="生图 / 上传 / 视频渲染的产出统一成一条流水线：唯一产物 ID → 送审 → 审核 → 发布"
        actions={
          <Button variant="outline" size="sm" className="h-8" onClick={handleRefresh}>
            <RefreshCcw className="mr-1.5 h-3.5 w-3.5" />
            刷新
          </Button>
        }
      />

      {/* 阶段统计条 */}
      <div className="grid grid-cols-2 gap-2 border border-border/60 bg-card/20 p-3 md:grid-cols-4 lg:grid-cols-8">
        <StatCell label="全部" value={stats?.total ?? 0} accent />
        {STAGE_ORDER.map((s) => (
          <StatCell
            key={s}
            label={STAGE_META[s]?.label ?? s}
            value={stats?.by_stage?.[s] ?? 0}
          />
        ))}
      </div>

      {/* 过滤器 */}
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">阶段</Label>
          <Select value={stage} onValueChange={setStage}>
            <SelectTrigger className="h-9 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              {STAGE_ORDER.map((s) => (
                <SelectItem key={s} value={s}>
                  {STAGE_META[s]?.label ?? s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">来源</Label>
          <Select value={source} onValueChange={setSource}>
            <SelectTrigger className="h-9 w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              {Object.entries(SOURCE_META).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">类型</Label>
          <Select value={kind} onValueChange={setKind}>
            <SelectTrigger className="h-9 w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部</SelectItem>
              {Object.entries(KIND_META).map(([k, v]) => (
                <SelectItem key={k} value={k}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">搜索</Label>
          <div className="flex items-center gap-1">
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleSearch()
              }}
              className="h-9 w-52"
              placeholder="标题 / 路径 / 来源 ID"
            />
            <Button variant="outline" size="sm" className="h-9" onClick={handleSearch}>
              <Search className="mr-1.5 h-3.5 w-3.5" />
              查询
            </Button>
          </div>
        </div>

        <div className="ml-auto text-xs text-muted-foreground">
          共 {listData?.total ?? 0} 条产物
        </div>
      </div>

      {/* 产物表 */}
      <Card className="border-border/70 bg-card/60">
        <CardContent className="p-0">
          {isLoading && items.length === 0 ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              加载中…
            </div>
          ) : items.length === 0 ? (
            <div className="py-10 text-center text-sm text-muted-foreground">
              暂无产物。去「AI 生图」生成一张，或在「素材管理」上传一个文件，产物会自动出现在这里。
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-16">预览</TableHead>
                  <TableHead>产物</TableHead>
                  <TableHead className="w-24">阶段</TableHead>
                  <TableHead className="w-28">来源</TableHead>
                  <TableHead className="w-40">关联记录</TableHead>
                  <TableHead className="w-32">创建时间</TableHead>
                  <TableHead className="w-40 text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((a) => (
                  <TableRow key={a.artifact_id}>
                    <TableCell>
                      <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded border border-border/60 bg-muted/30">
                        {isPreviewable(a) && previewUrl(a) ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={previewUrl(a)}
                            alt=""
                            className="h-full w-full object-cover"
                          />
                        ) : (a.kind === "video" ? (
                          <Video className="h-4 w-4 text-muted-foreground" />
                        ) : (
                          <ImageIcon className="h-4 w-4 text-muted-foreground" />
                        ))}
                      </div>
                    </TableCell>

                    <TableCell>
                      <div className="flex items-center gap-2">
                        <span className="truncate font-medium text-foreground">
                          {a.title || "（无标题）"}
                        </span>
                      </div>
                      <code className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                        {a.artifact_id}
                      </code>
                    </TableCell>

                    <TableCell>
                      <StageBadge stage={a.stage} />
                    </TableCell>

                    <TableCell>
                      <span className="text-xs text-muted-foreground">
                        {SOURCE_META[a.source || ""] ?? a.source ?? "-"}
                      </span>
                    </TableCell>

                    <TableCell>
                      <span className="text-[11px] text-muted-foreground">
                        {a.ref_type ? `${a.ref_type}#${a.ref_id}` : "-"}
                      </span>
                    </TableCell>

                    <TableCell>
                      <span className="text-xs text-muted-foreground">
                        {formatDate(a.created_at)}
                      </span>
                    </TableCell>

                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {(a.stage === "generated" || a.stage === "uploaded") && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-xs"
                            disabled={submitReview.isPending}
                            onClick={() => submitReview.mutate(a.artifact_id)}
                          >
                            <Send className="mr-1 h-3 w-3" />
                            送审
                          </Button>
                        )}
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-7 px-2 text-xs"
                          onClick={() => setDetail(a)}
                        >
                          <ChevronRight className="mr-1 h-3 w-3" />
                          详情
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* 详情弹窗 */}
      <Dialog open={!!detail} onOpenChange={(open) => !open && setDetail(null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Boxes className="h-4 w-4 text-primary" />
              产物详情
            </DialogTitle>
            <DialogDescription>
              {detail?.artifact_id} · 血缘（谁派生了谁）
            </DialogDescription>
          </DialogHeader>

          {detail && (
            <div className="space-y-4">
              <div className="flex gap-3">
                {isPreviewable(detail) && previewUrl(detail) ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={previewUrl(detail)}
                    alt=""
                    className="h-24 w-24 shrink-0 rounded border border-border/60 object-cover"
                  />
                ) : null}
                <dl className="grid flex-1 grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <Field label="阶段">
                    <StageBadge stage={detail.stage} />
                  </Field>
                  <Field label="类型">{KIND_META[detail.kind || ""] ?? detail.kind ?? "-"}</Field>
                  <Field label="来源">{SOURCE_META[detail.source || ""] ?? detail.source ?? "-"}</Field>
                  <Field label="关联记录">
                    {detail.ref_type ? `${detail.ref_type}#${detail.ref_id}` : "-"}
                  </Field>
                  <Field label="审核项">{detail.review_id || "-"}</Field>
                  <Field label="发布任务">{detail.publish_task_id || "-"}</Field>
                  <Field label="创建时间">{formatDate(detail.created_at)}</Field>
                  <Field label="更新时间">{formatDate(detail.updated_at)}</Field>
                  <Field label="路径" wide>
                    <code className="break-all">{detail.path || "-"}</code>
                  </Field>
                </dl>
              </div>

              <div className="space-y-2 border-t border-border/60 pt-3">
                <div className="flex items-center gap-1.5 text-xs font-medium text-foreground">
                  <GitBranch className="h-3.5 w-3.5" />
                  血缘
                </div>

                <div className="space-y-1 text-xs">
                  <div className="text-muted-foreground">
                    父产物：
                    {lineageData?.parent ? (
                      <code className="ml-1 text-foreground">
                        {lineageData.parent.artifact_id}
                      </code>
                    ) : (
                      <span className="ml-1">无（根产物）</span>
                    )}
                  </div>
                  <div className="text-muted-foreground">
                    派生：
                    {lineageData?.children?.length ? (
                      <span className="ml-1 flex flex-wrap gap-1">
                        {lineageData.children.map((c) => (
                          <Badge key={c.artifact_id} variant="outline" className="text-[10px]">
                            {c.artifact_id}
                          </Badge>
                        ))}
                      </span>
                    ) : (
                      <span className="ml-1">无</span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ============ 小组件 ============

function StatCell({
  label,
  value,
  accent,
}: {
  label: string
  value: number
  accent?: boolean
}) {
  return (
    <div className="flex flex-col gap-0.5 px-2 py-1">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span
        className={
          accent
            ? "font-terminal text-lg font-semibold text-primary"
            : "font-terminal text-lg font-semibold text-foreground"
        }
      >
        {value}
      </span>
    </div>
  )
}

function StageBadge({ stage }: { stage: string }) {
  const meta = STAGE_META[stage] ?? { label: stage || "-", variant: "secondary" as BadgeVariant }
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}

function Field({
  label,
  children,
  wide,
}: {
  label: string
  children: React.ReactNode
  wide?: boolean
}) {
  return (
    <div className={wide ? "col-span-2" : undefined}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-foreground">{children}</dd>
    </div>
  )
}
