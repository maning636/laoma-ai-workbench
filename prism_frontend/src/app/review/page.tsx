"use client"

// 审核队列 + 内容版本审批 + 敏感词库
// 参考同目录 tasks/publish/page.tsx 与 analytics/page.tsx 的既有风格：
//   - React Query 管理请求状态
//   - shadcn/ui 组件从 @/components/ui/* 导入
//   - Tailwind 语义化 class，禁止硬编码 bg-white / text-black
//   - 中文界面 + 中文注释

import { useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import {
  CheckCircle2,
  Eye,
  FileWarning,
  Layers,
  Loader2,
  Pencil,
  Plus,
  RefreshCcw,
  Shield,
  Trash2,
  Undo2,
  Upload,
  XCircle,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useToast } from "@/components/ui/use-toast"

// ============ 类型定义 ============

/** 审核项状态 */
type ReviewStatus =
  | "pending"
  | "in_review"
  | "approved"
  | "rejected"
  | "needs_edit"
  | "auto_approved"
  | "auto_rejected"

/** 审核优先级 */
type ReviewPriority = "low" | "normal" | "high" | "urgent"

/** 审核队列条目（后端 ReviewItem schema） */
interface ReviewItem {
  review_id: string
  task_id?: string
  campaign_id?: string
  platform?: number | string
  platform_name?: string
  account_id?: string
  status: ReviewStatus | string
  priority: ReviewPriority | string
  review_type?: string
  title?: string
  content?: string
  cover_url?: string
  risk_score?: number
  risk_factors?: string[]
  queue_position?: number
  reviewer?: string
  submitted_at?: string
  reviewed_at?: string
  decision_reason?: string
  decision_by?: string
  metadata?: Record<string, unknown>
  created_at?: string
}

/** 审核统计 */
interface ReviewStats {
  total?: number
  pending: number
  in_review: number
  approved: number
  rejected: number
  needs_edit: number
  auto_approved: number
  auto_rejected: number
}

/** 审核决策返回 */
interface ReviewDecision {
  review_id: string
  status: string
  reviewer?: string
  decision_reason?: string
  reviewed_at?: string
  /** 关联的统一产物 ID（送审自产物中心 / 生图 / 素材时存在） */
  artifact_id?: string
  /** 审核决策回写后的产物阶段 */
  artifact_stage?: string
}

/** 内容版本 */
interface ContentVariant {
  variant_id: string
  title?: string
  platform?: string | number
  platform_name?: string
  account_id?: string
  status?: string
  version?: number
  content?: string
  cover_url?: string
  campaign_id?: string
  created_at?: string
  updated_at?: string
  metadata?: Record<string, unknown>
}

/** 内容版本审核记录 */
interface VariantReview {
  review_id?: string
  variant_id?: string
  reviewer?: string
  decision?: string
  reason?: string
  created_at?: string
}

/** 敏感词 */
interface SensitiveWord {
  category: string
  word: string
}

// ============ 展示映射 ============

type BadgeVariant = "default" | "secondary" | "outline" | "destructive" | "accent"

const STATUS_META: Record<string, { label: string; variant: BadgeVariant }> = {
  pending: { label: "待审", variant: "secondary" },
  in_review: { label: "审核中", variant: "secondary" },
  approved: { label: "已通过", variant: "outline" },
  rejected: { label: "已拒绝", variant: "destructive" },
  needs_edit: { label: "需修改", variant: "outline" },
  auto_approved: { label: "自动通过", variant: "outline" },
  auto_rejected: { label: "自动拒绝", variant: "destructive" },
}

const PRIORITY_META: Record<string, { label: string; variant: BadgeVariant }> = {
  low: { label: "低", variant: "outline" },
  normal: { label: "普通", variant: "secondary" },
  high: { label: "高", variant: "default" },
  urgent: { label: "紧急", variant: "destructive" },
}

const VARIANT_STATUS_META: Record<string, { label: string; variant: BadgeVariant }> = {
  draft: { label: "草稿", variant: "outline" },
  submitted: { label: "已提交", variant: "secondary" },
  pending_review: { label: "待审", variant: "secondary" },
  in_review: { label: "审核中", variant: "secondary" },
  approved: { label: "已通过", variant: "outline" },
  rejected: { label: "已拒绝", variant: "destructive" },
  needs_edit: { label: "需修改", variant: "outline" },
  returned: { label: "已退回", variant: "outline" },
}

const SENSITIVE_CATEGORIES = ["其他", "色情", "赌博", "暴力", "政治", "广告"]

const DEFAULT_REVIEWER = "human-reviewer"

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? { label: status || "-", variant: "secondary" as BadgeVariant }
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}

function PriorityBadge({ priority }: { priority: string }) {
  const meta = PRIORITY_META[priority] ?? { label: priority || "-", variant: "outline" as BadgeVariant }
  return <Badge variant={meta.variant}>{meta.label}</Badge>
}

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

function snippet(text?: string, max = 90): string {
  if (!text) return "-"
  const flat = text.replace(/\s+/g, " ").trim()
  return flat.length > max ? flat.slice(0, max) + "…" : flat
}

// ============ 页面 ============

export default function ReviewPage() {
  const { toast } = useToast()

  // 顶部审核人标识，可修改；所有 approve/reject/edit 操作都写入 reviewer
  const [reviewer, setReviewer] = useState<string>(DEFAULT_REVIEWER)

  // ============= Tab 1: 审核队列 =============
  const [queueStatus, setQueueStatus] = useState<string>("all")
  const [queuePriority, setQueuePriority] = useState<string>("all")
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [batchReason, setBatchReason] = useState<string>("")
  const [detailItem, setDetailItem] = useState<ReviewItem | null>(null)
  const [detailReason, setDetailReason] = useState<string>("")

  // 队列
  const {
    data: queueData,
    isLoading: isLoadingQueue,
    refetch: refetchQueue,
  } = useQuery({
    queryKey: ["review-queue", queueStatus, queuePriority],
    queryFn: async () => {
      const params = new URLSearchParams({ limit: "200" })
      if (queueStatus !== "all") params.set("status", queueStatus)
      if (queuePriority !== "all") params.set("priority", queuePriority)
      const res = await fetch(`/api/v1/review/queue?${params.toString()}`)
      if (!res.ok) throw new Error(`队列加载失败 (HTTP ${res.status})`)
      const json: unknown = await res.json()
      // 兼容后端可能返回数组 / {data: [...]} / {items: [...]}
      if (Array.isArray(json)) return json as ReviewItem[]
      const obj = json as { data?: ReviewItem[]; items?: ReviewItem[]; list?: ReviewItem[] }
      return obj.data ?? obj.items ?? obj.list ?? []
    },
  })

  // 统计
  const { data: statsData, refetch: refetchStats } = useQuery({
    queryKey: ["review-stats"],
    queryFn: async () => {
      const res = await fetch("/api/v1/review/stats")
      if (!res.ok) throw new Error(`统计加载失败 (HTTP ${res.status})`)
      const json = (await res.json()) as ReviewStats & { data?: ReviewStats }
      return json?.data ?? json
    },
  })

  const queueItems: ReviewItem[] = queueData ?? []
  const stats: ReviewStats = statsData ?? {
    pending: 0,
    in_review: 0,
    approved: 0,
    rejected: 0,
    needs_edit: 0,
    auto_approved: 0,
    auto_rejected: 0,
  }

  const allVisibleChecked = queueItems.length > 0 && queueItems.every((it) => selectedIds.includes(it.review_id))
  const someVisibleChecked = queueItems.some((it) => selectedIds.includes(it.review_id))

  const toggleAll = (checked: boolean) => {
    if (checked) {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...queueItems.map((i) => i.review_id)])))
    } else {
      const removeSet = new Set(queueItems.map((i) => i.review_id))
      setSelectedIds((prev) => prev.filter((id) => !removeSet.has(id)))
    }
  }

  const toggleOne = (id: string, checked: boolean) => {
    setSelectedIds((prev) => (checked ? Array.from(new Set([...prev, id])) : prev.filter((x) => x !== id)))
  }

  // 单条操作：approve / reject / edit
  const singleAction = useMutation({
    mutationFn: async ({
      reviewId,
      action,
      reason,
    }: {
      reviewId: string
      action: "approve" | "reject" | "edit"
      reason: string
    }) => {
      const res = await fetch(`/api/v1/review/items/${reviewId}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer, reason }),
      })
      if (!res.ok) throw new Error(`操作失败 (HTTP ${res.status})`)
      return res.json() as Promise<ReviewDecision>
    },
    onSuccess: (data, vars) => {
      const msg =
        vars.action === "approve"
          ? "已通过"
          : vars.action === "reject"
            ? "已拒绝"
            : "已标记需要修改"
      // 产物阶段回写结果：审核决策会自动推进来源产物的阶段
      const stageHint = data.artifact_stage
        ? ` · 产物阶段 → ${data.artifact_stage}`
        : ""
      toast({
        title: `${msg}：${vars.reviewId.slice(0, 8)}…${stageHint}`,
        description: data.artifact_id ? `来源产物 ${data.artifact_id}` : undefined,
      })
      setDetailItem(null)
      setDetailReason("")
      void refetchQueue()
      void refetchStats()
    },
    onError: (err) => {
      toast({ variant: "destructive", title: "操作失败", description: String(err) })
    },
  })

  // 批量操作
  const batchAction = useMutation({
    mutationFn: async ({
      action,
      ids,
      reason,
    }: {
      action: "approve" | "reject"
      ids: string[]
      reason: string
    }) => {
      const path = action === "approve" ? "batch-approve" : "batch-reject"
      const res = await fetch(`/api/v1/review/${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ review_ids: ids, reviewer, reason }),
      })
      if (!res.ok) throw new Error(`批量操作失败 (HTTP ${res.status})`)
      return res.json() as Promise<{ approved?: number; rejected?: number }>
    },
    onSuccess: (data, vars) => {
      const n =
        vars.action === "approve"
          ? data.approved ?? vars.ids.length
          : data.rejected ?? vars.ids.length
      toast({
        title: `${vars.action === "approve" ? "批量通过" : "批量拒绝"}成功`,
        description: `处理 ${n} 条`,
      })
      setSelectedIds([])
      setBatchReason("")
      void refetchQueue()
      void refetchStats()
    },
    onError: (err) => {
      toast({ variant: "destructive", title: "批量操作失败", description: String(err) })
    },
  })

  // ============= Tab 2: 内容版本审批 =============
  const [variantReason, setVariantReason] = useState<string>("")

  const {
    data: variantsData,
    isLoading: isLoadingVariants,
    refetch: refetchVariants,
  } = useQuery({
    queryKey: ["content-variants"],
    queryFn: async () => {
      const res = await fetch("/api/v1/content-variants/variants/")
      if (!res.ok) throw new Error(`版本加载失败 (HTTP ${res.status})`)
      const json: unknown = await res.json()
      if (Array.isArray(json)) return json as ContentVariant[]
      const obj = json as { data?: ContentVariant[]; items?: ContentVariant[]; list?: ContentVariant[] }
      return obj.data ?? obj.items ?? obj.list ?? []
    },
  })

  const {
    data: reviewsData,
    isLoading: isLoadingReviews,
    refetch: refetchReviews,
  } = useQuery({
    queryKey: ["content-variant-reviews"],
    queryFn: async () => {
      const res = await fetch("/api/v1/content-variants/reviews/")
      if (!res.ok) throw new Error(`审核记录加载失败 (HTTP ${res.status})`)
      const json: unknown = await res.json()
      if (Array.isArray(json)) return json as VariantReview[]
      const obj = json as { data?: VariantReview[]; items?: VariantReview[]; list?: VariantReview[] }
      return obj.data ?? obj.items ?? obj.list ?? []
    },
  })

  const variants: ContentVariant[] = variantsData ?? []
  const reviews: VariantReview[] = reviewsData ?? []

  // 版本操作：submit / approve / reject / return
  const variantAction = useMutation({
    mutationFn: async ({
      variantId,
      action,
      reason,
    }: {
      variantId: string
      action: "submit" | "approve" | "reject" | "return"
      reason: string
    }) => {
      const res = await fetch(`/api/v1/content-variants/variants/${variantId}/${action}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reviewer, reason }),
      })
      if (!res.ok) throw new Error(`操作失败 (HTTP ${res.status})`)
      return res.json()
    },
    onSuccess: (_data, vars) => {
      const labelMap = {
        submit: "已提交审核",
        approve: "已通过",
        reject: "已拒绝",
        return: "已退回修改",
      } as const
      toast({ title: labelMap[vars.action] })
      void refetchVariants()
      void refetchReviews()
    },
    onError: (err) => {
      toast({ variant: "destructive", title: "操作失败", description: String(err) })
    },
  })

  // ============= Tab 3: 敏感词库 =============
  const [newWord, setNewWord] = useState("")
  const [newCategory, setNewCategory] = useState("其他")

  const {
    data: wordsData,
    isLoading: isLoadingWords,
    refetch: refetchWords,
  } = useQuery({
    queryKey: ["sensitive-words"],
    queryFn: async () => {
      const res = await fetch("/api/v1/fusion/moderation/sensitive-words")
      if (!res.ok) throw new Error(`敏感词加载失败 (HTTP ${res.status})`)
      const json: unknown = await res.json()
      if (Array.isArray(json)) return json as SensitiveWord[]
      const obj = json as { words?: SensitiveWord[]; data?: SensitiveWord[] }
      return obj.words ?? obj.data ?? []
    },
  })

  const words: SensitiveWord[] = wordsData ?? []

  const addWord = useMutation({
    mutationFn: async (payload: { word: string; category: string }) => {
      const res = await fetch("/api/v1/fusion/moderation/sensitive-words", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`新增失败 (HTTP ${res.status})`)
      return res.json()
    },
    onSuccess: () => {
      toast({ title: "已新增敏感词" })
      setNewWord("")
      void refetchWords()
    },
    onError: (err) => {
      toast({ variant: "destructive", title: "新增失败", description: String(err) })
    },
  })

  const deleteWord = useMutation({
    mutationFn: async ({ word, category }: SensitiveWord) => {
      const res = await fetch(
        `/api/v1/fusion/moderation/sensitive-words?category=${encodeURIComponent(category)}&word=${encodeURIComponent(word)}`,
        { method: "DELETE" },
      )
      if (!res.ok) throw new Error(`删除失败 (HTTP ${res.status})`)
      return res.json()
    },
    onSuccess: () => {
      toast({ title: "已删除" })
      void refetchWords()
    },
    onError: (err) => {
      toast({ variant: "destructive", title: "删除失败", description: String(err) })
    },
  })

  const handleRefreshAll = () => {
    void refetchQueue()
    void refetchStats()
    void refetchVariants()
    void refetchReviews()
    void refetchWords()
    toast({ title: "已刷新全部数据" })
  }

  // ============= 渲染 =============

  return (
    <div className="mx-auto max-w-[1440px] space-y-4 px-4 py-4">
      <PageHeader
        eyebrow="REVIEW · 审核工作流"
        title="审核队列"
        description="人工审核内容队列 · 内容版本审批 · 敏感词库"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Label className="text-xs text-muted-foreground">审核人</Label>
            <Input
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              className="h-8 w-40"
              placeholder="审核人标识"
            />
            <Button variant="outline" size="sm" className="h-8" onClick={handleRefreshAll}>
              <RefreshCcw className="mr-1.5 h-3.5 w-3.5" />
              全部刷新
            </Button>
          </div>
        }
      />

      <Tabs defaultValue="queue">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="queue">
            <Shield className="mr-1.5 h-3.5 w-3.5" />
            审核队列
          </TabsTrigger>
          <TabsTrigger value="variants">
            <Layers className="mr-1.5 h-3.5 w-3.5" />
            内容版本审批
          </TabsTrigger>
          <TabsTrigger value="words">
            <FileWarning className="mr-1.5 h-3.5 w-3.5" />
            敏感词库
          </TabsTrigger>
        </TabsList>

        {/* ---------- Tab 1: 审核队列 ---------- */}
        <TabsContent value="queue" className="space-y-4">
          {/* 统计条 */}
          <div className="grid grid-cols-2 gap-2 border border-border/60 bg-card/20 p-3 md:grid-cols-4 lg:grid-cols-8">
            <StatCell label="待审" value={stats.pending} accent />
            <StatCell label="审核中" value={stats.in_review} />
            <StatCell label="已通过" value={stats.approved} />
            <StatCell label="已拒绝" value={stats.rejected} />
            <StatCell label="需修改" value={stats.needs_edit} />
            <StatCell label="自动通过" value={stats.auto_approved} />
            <StatCell label="自动拒绝" value={stats.auto_rejected} />
            <StatCell label="合计" value={stats.total ?? queueItems.length} />
          </div>

          {/* 过滤器 + 批量栏 */}
          <div className="flex flex-wrap items-end gap-2">
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-muted-foreground">状态</Label>
              <Select value={queueStatus} onValueChange={setQueueStatus}>
                <SelectTrigger className="h-9 w-40">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部</SelectItem>
                  <SelectItem value="pending">待审</SelectItem>
                  <SelectItem value="in_review">审核中</SelectItem>
                  <SelectItem value="approved">已通过</SelectItem>
                  <SelectItem value="rejected">已拒绝</SelectItem>
                  <SelectItem value="needs_edit">需修改</SelectItem>
                  <SelectItem value="auto_approved">自动通过</SelectItem>
                  <SelectItem value="auto_rejected">自动拒绝</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1">
              <Label className="text-xs text-muted-foreground">优先级</Label>
              <Select value={queuePriority} onValueChange={setQueuePriority}>
                <SelectTrigger className="h-9 w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部</SelectItem>
                  <SelectItem value="low">低</SelectItem>
                  <SelectItem value="normal">普通</SelectItem>
                  <SelectItem value="high">高</SelectItem>
                  <SelectItem value="urgent">紧急</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {selectedIds.length > 0 && (
              <div className="ml-auto flex flex-wrap items-end gap-2">
                <Badge className="h-8 px-2">已选 {selectedIds.length} 条</Badge>
                <Input
                  value={batchReason}
                  onChange={(e) => setBatchReason(e.target.value)}
                  placeholder="批量处理理由（可选）"
                  className="h-9 w-56"
                />
                <Button
                  size="sm"
                  className="h-9"
                  disabled={batchAction.isPending || selectedIds.length === 0}
                  onClick={() =>
                    batchAction.mutate({ action: "approve", ids: selectedIds, reason: batchReason || "批量通过" })
                  }
                >
                  {batchAction.isPending ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <CheckCircle2 className="mr-1 h-4 w-4" />
                  )}
                  批量通过
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  className="h-9"
                  disabled={batchAction.isPending || selectedIds.length === 0}
                  onClick={() =>
                    batchAction.mutate({ action: "reject", ids: selectedIds, reason: batchReason || "批量拒绝" })
                  }
                >
                  {batchAction.isPending ? (
                    <Loader2 className="mr-1 h-4 w-4 animate-spin" />
                  ) : (
                    <XCircle className="mr-1 h-4 w-4" />
                  )}
                  批量拒绝
                </Button>
              </div>
            )}
          </div>

          {/* 表格 */}
          <Card>
            <CardContent className="p-0">
              {isLoadingQueue ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : queueItems.length === 0 ? (
                <div className="py-12 text-center text-sm text-muted-foreground">
                  当前筛选条件下暂无审核条目
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-10">
                        <Checkbox
                          checked={allVisibleChecked ? true : someVisibleChecked ? "indeterminate" : false}
                          onCheckedChange={(v) => toggleAll(v === true)}
                          aria-label="全选当前列表"
                        />
                      </TableHead>
                      <TableHead>标题 / 内容摘要</TableHead>
                      <TableHead className="w-36">来源产物</TableHead>
                      <TableHead>平台</TableHead>
                      <TableHead>账号</TableHead>
                      <TableHead>风险分</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>优先级</TableHead>
                      <TableHead>提交时间</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {queueItems.map((item) => {
                      const checked = selectedIds.includes(item.review_id)
                      return (
                        <TableRow key={item.review_id} className="align-top">
                          <TableCell>
                            <Checkbox
                              checked={checked}
                              onCheckedChange={(v) => toggleOne(item.review_id, v === true)}
                              aria-label="选择该审核项"
                            />
                          </TableCell>
                          <TableCell className="max-w-md">
                            <div className="truncate font-medium" title={item.title}>
                              {item.title || "(无标题)"}
                            </div>
                            <div className="truncate text-xs text-muted-foreground" title={item.content}>
                              {snippet(item.content)}
                            </div>
                          </TableCell>
                          {/* 来源产物（统一产物总线）：task_id 形如 art_xxx 即为产物 ID */}
                          <TableCell>
                            {item.task_id?.startsWith("art_") ? (
                              <a
                                href="/artifacts"
                                title={`来源产物 ${item.task_id}（点击打开产物中心）`}
                                className="font-mono text-[11px] text-primary underline-offset-2 hover:underline"
                              >
                                {item.task_id}
                              </a>
                            ) : (
                              <span className="font-mono text-[11px] text-muted-foreground">
                                {item.task_id || "-"}
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="whitespace-nowrap">
                            <Badge variant="outline">{item.platform_name || "未知平台"}</Badge>
                          </TableCell>
                          <TableCell className="max-w-[120px] truncate text-xs text-muted-foreground">
                            {item.account_id || "-"}
                          </TableCell>
                          <TableCell>
                            {typeof item.risk_score === "number" ? (
                              <span
                                className={`font-mono text-sm ${
                                  item.risk_score >= 70
                                    ? "text-red-500"
                                    : item.risk_score >= 40
                                      ? "text-orange-500"
                                      : "text-muted-foreground"
                                }`}
                              >
                                {item.risk_score}
                              </span>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={item.status} />
                          </TableCell>
                          <TableCell>
                            <PriorityBadge priority={item.priority} />
                          </TableCell>
                          <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                            {formatDate(item.submitted_at ?? item.created_at)}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2"
                                disabled={singleAction.isPending}
                                title="通过"
                                onClick={() =>
                                  singleAction.mutate({
                                    reviewId: item.review_id,
                                    action: "approve",
                                    reason: "人工审核通过",
                                  })
                                }
                              >
                                <CheckCircle2 className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2 text-red-500 hover:text-red-500"
                                disabled={singleAction.isPending}
                                title="拒绝"
                                onClick={() =>
                                  singleAction.mutate({
                                    reviewId: item.review_id,
                                    action: "reject",
                                    reason: "人工审核拒绝",
                                  })
                                }
                              >
                                <XCircle className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2"
                                disabled={singleAction.isPending}
                                title="要求修改"
                                onClick={() =>
                                  singleAction.mutate({
                                    reviewId: item.review_id,
                                    action: "edit",
                                    reason: "需要修改",
                                  })
                                }
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-8 px-2"
                                title="查看详情"
                                onClick={() => {
                                  setDetailItem(item)
                                  setDetailReason("")
                                }}
                              >
                                <Eye className="h-4 w-4" />
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---------- Tab 2: 内容版本审批 ---------- */}
        <TabsContent value="variants" className="space-y-4">
          <div className="flex flex-wrap items-end gap-2">
            <Label className="mb-1.5 text-xs text-muted-foreground">操作理由</Label>
            <Input
              value={variantReason}
              onChange={(e) => setVariantReason(e.target.value)}
              placeholder="（可选）本次操作的理由，写入后端 reviewer/reason"
              className="h-9 w-full max-w-md"
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">内容版本列表</CardTitle>
              <CardDescription>
                数据来自 /api/v1/content-variants/variants/；每条版本可执行 提交 / 通过 / 拒绝 / 退回 操作。
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {isLoadingVariants ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : variants.length === 0 ? (
                <div className="py-12 text-center text-sm text-muted-foreground">暂无内容版本</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>版本 ID</TableHead>
                      <TableHead>标题</TableHead>
                      <TableHead>平台</TableHead>
                      <TableHead>版本</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>更新时间</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {variants.map((v) => {
                      const meta =
                        VARIANT_STATUS_META[v.status ?? ""] ??
                        { label: v.status || "-", variant: "secondary" as BadgeVariant }
                      return (
                        <TableRow key={v.variant_id}>
                          <TableCell className="font-mono text-xs">{v.variant_id.slice(0, 10)}</TableCell>
                          <TableCell className="max-w-md truncate">
                            {v.title || snippet(v.content) || "-"}
                          </TableCell>
                          <TableCell>{v.platform_name || v.platform || "-"}</TableCell>
                          <TableCell>{v.version != null ? `v${v.version}` : "-"}</TableCell>
                          <TableCell>
                            <Badge variant={meta.variant}>{meta.label}</Badge>
                          </TableCell>
                          <TableCell className="text-xs text-muted-foreground">
                            {formatDate(v.updated_at ?? v.created_at)}
                          </TableCell>
                          <TableCell className="text-right">
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2"
                                disabled={variantAction.isPending}
                                onClick={() =>
                                  variantAction.mutate({
                                    variantId: v.variant_id,
                                    action: "submit",
                                    reason: variantReason || "提交审核",
                                  })
                                }
                              >
                                <Upload className="mr-1 h-4 w-4" />
                                提交
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2"
                                disabled={variantAction.isPending}
                                onClick={() =>
                                  variantAction.mutate({
                                    variantId: v.variant_id,
                                    action: "approve",
                                    reason: variantReason || "通过",
                                  })
                                }
                              >
                                <CheckCircle2 className="mr-1 h-4 w-4" />
                                通过
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2 text-red-500 hover:text-red-500"
                                disabled={variantAction.isPending}
                                onClick={() =>
                                  variantAction.mutate({
                                    variantId: v.variant_id,
                                    action: "reject",
                                    reason: variantReason || "拒绝",
                                  })
                                }
                              >
                                <XCircle className="mr-1 h-4 w-4" />
                                拒绝
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                className="h-8 px-2"
                                disabled={variantAction.isPending}
                                onClick={() =>
                                  variantAction.mutate({
                                    variantId: v.variant_id,
                                    action: "return",
                                    reason: variantReason || "退回修改",
                                  })
                                }
                              >
                                <Undo2 className="mr-1 h-4 w-4" />
                                退回
                              </Button>
                            </div>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">审核记录</CardTitle>
              <CardDescription>数据来自 /api/v1/content-variants/reviews/</CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {isLoadingReviews ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : reviews.length === 0 ? (
                <div className="py-12 text-center text-sm text-muted-foreground">暂无审核记录</div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>版本</TableHead>
                      <TableHead>决策</TableHead>
                      <TableHead>审核人</TableHead>
                      <TableHead>理由</TableHead>
                      <TableHead>时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {reviews.map((r, i) => (
                      <TableRow key={r.review_id ?? i}>
                        <TableCell className="font-mono text-xs">
                          {(r.variant_id ?? "").slice(0, 10) || "-"}
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline">{r.decision || "-"}</Badge>
                        </TableCell>
                        <TableCell>{r.reviewer || "-"}</TableCell>
                        <TableCell className="max-w-md truncate text-xs text-muted-foreground">
                          {r.reason || "-"}
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground">{formatDate(r.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---------- Tab 3: 敏感词库 ---------- */}
        <TabsContent value="words" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Shield className="h-4 w-4" />
                敏感词库（{words.length} 条）
              </CardTitle>
              <CardDescription>
                数据来自 /api/v1/fusion/moderation/sensitive-words，可新增或删除。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-col gap-1">
                  <Label className="text-xs text-muted-foreground">分类</Label>
                  <Select value={newCategory} onValueChange={setNewCategory}>
                    <SelectTrigger className="h-9 w-32">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {SENSITIVE_CATEGORIES.map((c) => (
                        <SelectItem key={c} value={c}>
                          {c}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex min-w-[220px] flex-1 flex-col gap-1">
                  <Label className="text-xs text-muted-foreground">敏感词</Label>
                  <Input
                    value={newWord}
                    onChange={(e) => setNewWord(e.target.value)}
                    placeholder="输入敏感词后回车新增"
                    className="h-9"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && newWord.trim()) {
                        addWord.mutate({ word: newWord.trim(), category: newCategory })
                      }
                    }}
                  />
                </div>
                <Button
                  className="h-9"
                  disabled={!newWord.trim() || addWord.isPending}
                  onClick={() => addWord.mutate({ word: newWord.trim(), category: newCategory })}
                >
                  <Plus className="mr-1 h-4 w-4" />
                  新增
                </Button>
              </div>

              {isLoadingWords ? (
                <div className="flex items-center justify-center py-12">
                  <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
              ) : words.length === 0 ? (
                <div className="py-8 text-center text-sm text-muted-foreground">词库为空</div>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {words.map((w, i) => (
                    <Badge key={`${w.category}-${w.word}-${i}`} variant="outline" className="pr-1">
                      <span>
                        {w.word} <span className="text-muted-foreground">· {w.category}</span>
                      </span>
                      <button
                        type="button"
                        aria-label="删除"
                        onClick={() => deleteWord.mutate(w)}
                        className="ml-1.5 text-muted-foreground transition-colors hover:text-red-500"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </Badge>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* 详情对话框：仅用于队列 Tab */}
      <Dialog open={!!detailItem} onOpenChange={(open) => !open && setDetailItem(null)}>
        <DialogContent className="max-w-2xl">
          {detailItem && (
            <>
              <DialogHeader>
                <DialogTitle>{detailItem.title || "(无标题)"}</DialogTitle>
                <DialogDescription>
                  审核 ID：{detailItem.review_id.slice(0, 10)} · 平台：
                  {detailItem.platform_name || "-"} · 提交：
                  {formatDate(detailItem.submitted_at)}
                </DialogDescription>
              </DialogHeader>
              <div className="max-h-[55vh] space-y-3 overflow-y-auto pr-1">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="mb-0.5 text-xs text-muted-foreground">账号</div>
                    <div>{detailItem.account_id || "-"}</div>
                  </div>
                  <div>
                    <div className="mb-0.5 text-xs text-muted-foreground">任务 ID</div>
                    <div className="break-all font-mono text-xs">{detailItem.task_id || "-"}</div>
                  </div>
                  <div>
                    <div className="mb-0.5 text-xs text-muted-foreground">状态 / 优先级</div>
                    <div className="flex gap-1">
                      <StatusBadge status={detailItem.status} />
                      <PriorityBadge priority={detailItem.priority} />
                    </div>
                  </div>
                  <div>
                    <div className="mb-0.5 text-xs text-muted-foreground">风险分</div>
                    <div>
                      {typeof detailItem.risk_score === "number" ? (
                        <span className="font-mono">{detailItem.risk_score}</span>
                      ) : (
                        "-"
                      )}
                    </div>
                  </div>
                </div>

                {detailItem.risk_factors && detailItem.risk_factors.length > 0 && (
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">风险因子</div>
                    <div className="flex flex-wrap gap-1">
                      {detailItem.risk_factors.map((f, i) => (
                        <Badge key={i} variant="outline">
                          {f}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <div className="mb-1 text-xs text-muted-foreground">内容全文</div>
                  <div className="whitespace-pre-wrap break-words rounded-lg border border-border/60 bg-muted/30 p-3 text-sm">
                    {detailItem.content || "(空)"}
                  </div>
                </div>

                {detailItem.cover_url && (
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">封面</div>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={detailItem.cover_url}
                      alt="封面预览"
                      className="max-h-48 rounded-lg border border-border/60"
                    />
                  </div>
                )}

                {detailItem.decision_reason && (
                  <div>
                    <div className="mb-1 text-xs text-muted-foreground">上次决策理由</div>
                    <div className="text-sm text-muted-foreground">
                      {detailItem.decision_reason}
                      {detailItem.decision_by ? ` · ${detailItem.decision_by}` : ""}
                    </div>
                  </div>
                )}

                <div>
                  <Label className="text-xs text-muted-foreground">本次操作理由</Label>
                  <Textarea
                    value={detailReason}
                    onChange={(e) => setDetailReason(e.target.value)}
                    placeholder="填写审核理由（可选）"
                    className="mt-1 min-h-[72px]"
                  />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDetailItem(null)}>
                  关闭
                </Button>
                <Button
                  variant="destructive"
                  disabled={singleAction.isPending}
                  onClick={() =>
                    detailItem &&
                    singleAction.mutate({
                      reviewId: detailItem.review_id,
                      action: "reject",
                      reason: detailReason || "人工审核拒绝",
                    })
                  }
                >
                  <XCircle className="mr-1 h-4 w-4" />
                  拒绝
                </Button>
                <Button
                  variant="secondary"
                  disabled={singleAction.isPending}
                  onClick={() =>
                    detailItem &&
                    singleAction.mutate({
                      reviewId: detailItem.review_id,
                      action: "edit",
                      reason: detailReason || "需要修改",
                    })
                  }
                >
                  <Pencil className="mr-1 h-4 w-4" />
                  要求修改
                </Button>
                <Button
                  disabled={singleAction.isPending}
                  onClick={() =>
                    detailItem &&
                    singleAction.mutate({
                      reviewId: detailItem.review_id,
                      action: "approve",
                      reason: detailReason || "人工审核通过",
                    })
                  }
                >
                  <CheckCircle2 className="mr-1 h-4 w-4" />
                  通过
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ============ 小组件 ============

/** 统计单元格：用于队列统计条 */
function StatCell({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-xl border border-border/60 bg-card px-3 py-2">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`text-lg font-semibold ${accent ? "text-primary" : "text-foreground"}`}>{value}</div>
    </div>
  )
}
