"use client"

/**
 * M1 前端 · AI 生图工作台（/fusion/image-studio）
 *
 * 整合：
 *   - M1 后端：`GET /api/v1/ai-design/capabilities` + `POST /generate` + `GET /records`
 *   - M2 智能体：`GET /api/v1/ai-design/agents` + `/quota`（复用 M2 authFetch 的 JWT 注入模式）
 *   - M4 场景引导：`components/wizard/scenarios.tsx` 里 AI_IMAGE_SCENARIO.target 指向本页
 *   - M5 编辑器：生成结果点击"编辑"跳转到 `/tools/image-editor?url=<imgUrl>`
 *
 * 设计取舍：
 *   - 素材上传仅做本地预览（UI 骨架），当前 M1 全部 provider 的 maxReferenceImages=0；
 *     UI 上放"上传原图"是为了保留后续扩参考图能力的骨架位。
 *   - 后端要求 JWT（M2 hardening 后）；这里对齐 agent-studio-panel 的 authFetch 模式，
 *     从 cloudAuth.getAccessToken() 拉 token 注入 Authorization header。
 *   - 生成请求带 idempotency_key（客户端生成 UUID-like 字符串），后端目前未做幂等去重，
 *     但字段已在契约里，前端提前传上，便于后端接入时不破坏前端。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Bot,
  Coins,
  Download,
  Image as ImageIcon,
  Loader2,
  LogIn,
  PenSquare,
  Plus,
  RefreshCw,
  Send,
  Sparkles,
  Trash2,
  UploadCloud,
  Wand2,
} from "lucide-react"
import { PageHeader } from "@/components/layout/page-scaffold"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useToast } from "@/components/ui/use-toast"
import { API_ENDPOINTS } from "@/lib/env"
import { cloudAuth } from "@/lib/cloud-auth"
import {
  AI_IMAGE_UNIT_POINTS,
  ACCEPTED_IMAGE_TYPES,
  EMPTY_DRAFT,
  IMAGE_TYPES,
  MAX_COUNT_PER_REQUEST,
  MAX_REFERENCE_IMAGES,
  NO_AGENT_VALUE,
  buildEditorUrl,
  buildGeneratePayload,
  deriveLimits,
  estimatePoints,
  filterAcceptedFiles,
  findModel,
  imageTypeHint,
  makeIdempotencyKey,
  normalizeAspectRatio,
  normalizeRecord,
  validateDraft,
  type AiDesignCapabilities,
  type AiDesignGenerateResponse,
  type AiDesignModel,
  type AiDesignRecord,
  type AiDesignRecordsPage,
  type ImageStudioDraft,
  type ReferencePreview,
} from "@/lib/image-studio"
import type { AgentPublic, AgentQuota } from "@/lib/agent-studio"

// ──────────────────────────────────────────────────────────────
// 端点常量
// ──────────────────────────────────────────────────────────────

const CAPABILITIES_URL = `${API_ENDPOINTS.base}/api/v1/ai-design/capabilities`
const GENERATE_URL = `${API_ENDPOINTS.base}/api/v1/ai-design/generate`
const RECORDS_URL = `${API_ENDPOINTS.base}/api/v1/ai-design/records`
const AGENTS_URL = `${API_ENDPOINTS.base}/api/v1/ai-design/agents`
const AGENTS_QUOTA_URL = `${AGENTS_URL}/quota`

// ──────────────────────────────────────────────────────────────
// authFetch（复用 M2 agent-studio-panel 的模式；不重复造轮子）
// ──────────────────────────────────────────────────────────────

async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const token = await cloudAuth.getAccessToken()
  const headers = new Headers(init.headers)
  if (token) headers.set("Authorization", `Bearer ${token}`)
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  return fetch(url, { ...init, headers })
}

// ──────────────────────────────────────────────────────────────
// 主组件
// ──────────────────────────────────────────────────────────────

export default function ImageStudioPage() {
  const { toast } = useToast()
  const [draft, setDraft] = useState<ImageStudioDraft>(EMPTY_DRAFT)

  // capabilities
  const [models, setModels] = useState<AiDesignModel[]>([])
  const [modelsLoading, setModelsLoading] = useState(true)
  const [unauthed, setUnauthed] = useState(false)

  // agents (M2)
  const [agents, setAgents] = useState<AgentPublic[]>([])
  const [quota, setQuota] = useState<AgentQuota | null>(null)

  // generate state
  const [generating, setGenerating] = useState(false)
  const [lastResult, setLastResult] = useState<AiDesignGenerateResponse | null>(null)
  const [errorMsg, setErrorMsg] = useState<string>("")

  // records
  const [records, setRecords] = useState<AiDesignRecord[]>([])
  const [recordsTotal, setRecordsTotal] = useState(0)
  const [recordsLoading, setRecordsLoading] = useState(false)

  const fileInputRef = useRef<HTMLInputElement | null>(null)

  const currentModel = useMemo(
    () => findModel(models, draft.modelKey),
    [models, draft.modelKey],
  )
  const limits = useMemo(() => deriveLimits(currentModel), [currentModel])

  // 切换模型时：aspectRatio 若不被支持则归位到第一个；count 若超限则钳住
  useEffect(() => {
    const nextRatio = normalizeAspectRatio(draft.aspectRatio, limits.supportedRatios)
    setDraft((prev) => ({
      ...prev,
      aspectRatio: nextRatio,
      count: Math.min(Math.max(prev.count, 1), limits.maxCount),
    }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limits.supportedRatios, limits.maxCount])

  // ── 初始加载：capabilities + agents + quota + records ──
  const loadAll = useCallback(async () => {
    setModelsLoading(true)
    try {
      const [capRes, agentRes, quotaRes] = await Promise.all([
        authFetch(CAPABILITIES_URL),
        authFetch(AGENTS_URL),
        authFetch(AGENTS_QUOTA_URL),
      ])
      if (capRes.status === 401 || agentRes.status === 401 || quotaRes.status === 401) {
        setUnauthed(true)
      } else {
        setUnauthed(false)
      }
      if (capRes.ok) {
        const d = (await capRes.json()) as AiDesignCapabilities
        setModels(d.models ?? [])
      }
      if (agentRes.ok) {
        const d = await agentRes.json()
        setAgents(Array.isArray(d.agents) ? d.agents : [])
      }
      if (quotaRes.ok) setQuota(await quotaRes.json())
    } catch (e) {
      console.error(e)
    } finally {
      setModelsLoading(false)
    }
    void loadRecords()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadRecords = useCallback(async () => {
    setRecordsLoading(true)
    try {
      const r = await authFetch(`${RECORDS_URL}?current=1&size=10`)
      if (r.ok) {
        const d = (await r.json()) as AiDesignRecordsPage
        setRecords(Array.isArray(d.records) ? d.records : [])
        setRecordsTotal(Number(d.total ?? 0))
      }
    } catch (e) {
      console.error(e)
    } finally {
      setRecordsLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  // ── 素材上传（本地预览；不真的上传后端）──
  const onFilesPicked = useCallback(
    (files: File[]) => {
      const accepted = filterAcceptedFiles(files)
      const rejected = files.length - accepted.length
      if (rejected > 0) {
        toast({
          title: `${rejected} 个文件被忽略`,
          description: "仅支持 JPG / PNG / WebP",
          variant: "destructive",
        })
      }
      const remain = MAX_REFERENCE_IMAGES - draft.referencePreview.length
      if (remain <= 0) {
        toast({ title: "已达最大上传数", description: `最多 ${MAX_REFERENCE_IMAGES} 张`, variant: "destructive" })
        return
      }
      const toAdd = accepted.slice(0, Math.max(0, remain))
      Promise.all(
        toAdd.map(
          (f) =>
            new Promise<ReferencePreview>((resolve) => {
              const reader = new FileReader()
              reader.onload = () => {
                const dataUrl = typeof reader.result === "string" ? reader.result : ""
                if (!dataUrl) return
                resolve({
                  id: `${Date.now()}_${f.name}`,
                  fileName: f.name,
                  dataUrl,
                  size: f.size,
                })
              }
              reader.readAsDataURL(f)
            }),
        ),
      ).then((added) => {
        setDraft((prev) => ({
          ...prev,
          referencePreview: [...prev.referencePreview, ...added].slice(0, MAX_REFERENCE_IMAGES),
        }))
      })
    },
    [draft.referencePreview.length, toast],
  )

  const removeRef = (id: string) => {
    setDraft((prev) => ({
      ...prev,
      referencePreview: prev.referencePreview.filter((r) => r.id !== id),
    }))
  }

  // ── 生成 ──
  const handleGenerate = async () => {
    const err = validateDraft(draft, currentModel)
    if (err) {
      toast({ title: "无法生成", description: err, variant: "destructive" })
      return
    }
    setGenerating(true)
    setErrorMsg("")
    try {
      const payload = buildGeneratePayload(draft, { idempotencyKey: makeIdempotencyKey() })
      const r = await authFetch(GENERATE_URL, {
        method: "POST",
        body: JSON.stringify(payload),
      })
      const data = await r.json().catch(() => null)
      if (!r.ok || !data) {
        const detail = data?.detail || data?.message || `生成失败（HTTP ${r.status}）`
        const msg = typeof detail === "string" ? detail : JSON.stringify(detail)
        setErrorMsg(msg)
        toast({ title: "生成失败", description: msg, variant: "destructive" })
        return
      }
      const resp = data as AiDesignGenerateResponse
      setLastResult(resp)
      toast({
        title: "生成完成",
        description: `${resp.model_key} · ${resp.images?.length ?? 0} 张 · 消耗 ${resp.points?.total ?? "?"} 积分`,
      })
      void loadRecords()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setErrorMsg(msg)
      toast({ title: "生成失败", description: msg, variant: "destructive" })
    } finally {
      setGenerating(false)
    }
  }

  // ── UI 派生 ──
  const pointsEstimate = estimatePoints(draft.count)
  const validationErr = validateDraft(draft, currentModel)
  const canGenerate =
    !generating && !modelsLoading && !!currentModel && !validationErr

  const activeAgent = draft.agentId
    ? agents.find((a) => a.id === draft.agentId)
    : null

  // 选择模型后，将默认宽高比对齐到该模型第一个支持的
  const handleModelChange = (key: string) => {
    const m = findModel(models, key)
    const ratio = m && m.supportedAspectRatios.length > 0 ? m.supportedAspectRatios[0] : draft.aspectRatio
    setDraft((prev) => ({
      ...prev,
      modelKey: key,
      aspectRatio: ratio,
      count: Math.min(Math.max(prev.count, 1), m ? m.maxOutputCount : prev.count),
    }))
  }

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="FUSION · M1"
        title="AI 生图工作台"
        description="对齐澜途 AI 图片设计 · 模型/宽高比/智能体/prompt/类型 → 生成 → 编辑"
        actions={
          <Button onClick={() => void loadAll()} disabled={modelsLoading}>
            <RefreshCw className={`h-4 w-4 mr-2 ${modelsLoading ? "animate-spin" : ""}`} />
            刷新
          </Button>
        }
      />

      <div className="mx-auto max-w-7xl space-y-4 px-6 py-6">
        {unauthed && (
          <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600 dark:text-amber-400">
            <LogIn className="h-3.5 w-3.5 shrink-0" />
            <span>
              AI 生图与智能体接口已启用 JWT 鉴权。请先登录以查看模型能力、生成图片、调用智能体。
            </span>
            <a href="/login" className="underline underline-offset-2">
              前往登录 →
            </a>
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[440px_minmax(0,1fr)]">
          {/* ─────────────────── 左侧：配置区 ─────────────────── */}
          <Card className="border-border/70 bg-card/60">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <Sparkles className="h-4 w-4 text-primary" />
                生成配置
                <Badge variant="outline" className="text-xs">M1 · AI 生图</Badge>
              </CardTitle>
              <CardDescription>
                模型能力来自 `/ai-design/capabilities`；生成调用 `/ai-design/generate`。
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* 上传原图（本地预览；UI 骨架） */}
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs">
                  <span className="font-medium">素材图（本地预览，可选）</span>
                  <span className="text-muted-foreground">
                    {draft.referencePreview.length}/{MAX_REFERENCE_IMAGES} · JPG/PNG/WebP
                  </span>
                </div>
                <div
                  className="flex cursor-pointer items-center justify-center rounded-md border border-dashed border-border/70 bg-background/30 px-3 py-4 text-xs text-muted-foreground hover:bg-background/50"
                  onClick={() => fileInputRef.current?.click()}
                >
                  <UploadCloud className="mr-2 h-4 w-4" />
                  拖拽或点击上传素材（JPG / PNG / WebP，最多 {MAX_REFERENCE_IMAGES} 张）
                  <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    multiple
                    accept={ACCEPTED_IMAGE_TYPES.join(",")}
                    onChange={(e) => {
                      const files = Array.from(e.target.files ?? [])
                      onFilesPicked(files)
                      e.target.value = ""
                    }}
                  />
                </div>
                {draft.referencePreview.length > 0 && (
                  <div className="grid grid-cols-4 gap-2">
                    {draft.referencePreview.map((r) => (
                      <div key={r.id} className="group relative aspect-square overflow-hidden rounded border border-border/60 bg-muted/40">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={r.dataUrl} alt={r.fileName} className="h-full w-full object-cover" />
                        <button
                          type="button"
                          className="absolute right-0.5 top-0.5 rounded bg-black/60 p-0.5 text-white opacity-0 transition group-hover:opacity-100"
                          onClick={() => removeRef(r.id)}
                          title="移除"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
                {currentModel && currentModel.maxReferenceImages === 0 && (
                  <div className="text-[11px] text-muted-foreground">
                    当前模型不支持参考图，仅作本地预览；后端会忽略此字段。
                  </div>
                )}
              </div>

              {/* 基础设置 */}
              <div className="space-y-2">
                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <label className="text-xs">模型 <span className="text-red-500">*</span></label>
                    <Select
                      value={draft.modelKey || "__placeholder__"}
                      onValueChange={(v) => handleModelChange(v === "__placeholder__" ? "" : v)}
                    >
                      <SelectTrigger className="h-10">
                        <SelectValue placeholder="选择模型" />
                      </SelectTrigger>
                      <SelectContent>
                        {modelsLoading && models.length === 0 && (
                          <SelectItem value="__loading__" disabled>加载中…</SelectItem>
                        )}
                        {!modelsLoading && models.length === 0 && (
                          <SelectItem value="__empty__" disabled>（未取到模型，请刷新或登录）</SelectItem>
                        )}
                        {models.map((m) => (
                          <SelectItem key={m.modelKey} value={m.modelKey}>
                            <span className="flex items-center gap-1.5">
                              <ImageIcon className="h-3 w-3 text-primary" />
                              {m.displayName}
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs">宽高比</label>
                    <Select value={draft.aspectRatio} onValueChange={(v) => setDraft((prev) => ({ ...prev, aspectRatio: v }))}>
                      <SelectTrigger className="h-10">
                        <SelectValue placeholder="宽高比" />
                      </SelectTrigger>
                      <SelectContent>
                        {limits.supportedRatios.map((r) => (
                          <SelectItem key={r} value={r}>{r}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div className="space-y-1">
                    <label className="text-xs">生成张数（1-{limits.maxCount}）</label>
                    <Input
                      type="number"
                      min={1}
                      max={limits.maxCount}
                      value={draft.count}
                      onChange={(e) => {
                        const n = Number.parseInt(e.target.value, 10)
                        setDraft((prev) => ({
                          ...prev,
                          count: Number.isNaN(n) ? 1 : Math.min(Math.max(n, 1), limits.maxCount),
                        }))
                      }}
                      className="h-10"
                    />
                  </div>

                  <div className="space-y-1">
                    <label className="text-xs">智能体（可选）</label>
                    <Select
                      value={draft.agentId || NO_AGENT_VALUE}
                      onValueChange={(v) => setDraft((prev) => ({ ...prev, agentId: v === NO_AGENT_VALUE ? "" : v }))}
                    >
                      <SelectTrigger className="h-10">
                        <SelectValue placeholder="不使用智能体" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={NO_AGENT_VALUE}>
                          <span className="flex items-center gap-1.5">
                            <Bot className="h-3 w-3" />不使用智能体
                          </span>
                        </SelectItem>
                        {agents.length === 0 && (
                          <SelectItem value="__empty__" disabled>（暂无智能体，可在 AI Agent Studio 创建）</SelectItem>
                        )}
                        {agents.map((a) => (
                          <SelectItem key={a.id} value={a.id}>
                            <span className="flex items-center gap-1.5">
                              <Sparkles className="h-3 w-3 text-primary" />
                              {a.name}
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {quota && (
                      <div className="text-[11px] text-muted-foreground">
                        智能体配额：{quota.used}/{quota.limit}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* 图片类型 */}
              <div className="space-y-2">
                <label className="text-xs font-medium">图片类型（可选，作为 prompt 提示）</label>
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  {IMAGE_TYPES.map((t) => {
                    const on = draft.imageType === t.id
                    return (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() =>
                          setDraft((prev) => ({ ...prev, imageType: on ? "none" : t.id }))
                        }
                        title={t.description}
                        className={
                          "rounded-md border px-2 py-1.5 text-xs transition-colors " +
                          (on
                            ? "border-primary/50 bg-primary/10 text-foreground"
                            : "border-border/60 bg-background/40 text-muted-foreground hover:text-foreground")
                        }
                      >
                        {t.label}
                      </button>
                    )
                  })}
                </div>
                {draft.imageType !== "none" && imageTypeHint(draft.imageType) && (
                  <div className="text-[11px] text-muted-foreground">{imageTypeHint(draft.imageType)}</div>
                )}
              </div>

              {/* Prompt */}
              <div className="space-y-1">
                <div className="flex items-center justify-between text-xs">
                  <label className="font-medium">Prompt <span className="text-red-500">*</span></label>
                  <span className="text-muted-foreground">{draft.prompt.length} 字</span>
                </div>
                <Textarea
                  value={draft.prompt}
                  onChange={(e) => setDraft((prev) => ({ ...prev, prompt: e.target.value }))}
                  placeholder="描述你想生成的图片内容……"
                  className="min-h-[110px]"
                  maxLength={2000}
                />
              </div>

              {/* 积分估算 + 生成按钮 */}
              <div className="space-y-2 rounded-md border border-border/60 bg-background/40 p-3">
                <div className="flex items-center justify-between text-xs">
                  <span className="flex items-center gap-1 text-muted-foreground">
                    <Coins className="h-3.5 w-3.5" />预计消耗积分
                  </span>
                  <span className="font-mono font-medium text-foreground">
                    {draft.count} × {AI_IMAGE_UNIT_POINTS} = {pointsEstimate}
                  </span>
                </div>
                <Button
                  className="w-full"
                  size="lg"
                  onClick={() => void handleGenerate()}
                  disabled={!canGenerate}
                  title={validationErr || "生成"}
                >
                  {generating ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />生成中…
                    </>
                  ) : (
                    <>
                      <Wand2 className="mr-2 h-4 w-4" />开始生成
                    </>
                  )}
                </Button>
                {validationErr && (
                  <div className="text-xs text-amber-600 dark:text-amber-400">{validationErr}</div>
                )}
                {errorMsg && (
                  <div className="text-xs text-red-600 dark:text-red-400">{errorMsg}</div>
                )}
              </div>
            </CardContent>
          </Card>

          {/* ─────────────────── 右侧：结果区 ─────────────────── */}
          <div className="space-y-4">
            <Card className="border-border/70 bg-card/60">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <PenSquare className="h-4 w-4 text-primary" />
                    生成结果
                    {lastResult && (
                      <Badge variant="outline" className="text-xs">{lastResult.task_id}</Badge>
                    )}
                  </CardTitle>
                  <span className="text-xs text-muted-foreground">
                    {generating ? "生成中…" : lastResult ? `${lastResult.images?.length ?? 0} 张` : "待生成"}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {generating && (
                  <div className="flex items-center justify-center gap-2 rounded-md border border-border/60 bg-background/40 py-12 text-sm text-muted-foreground">
                    <Loader2 className="h-5 w-5 animate-spin" />正在生成 {draft.count} 张图片…
                  </div>
                )}
                {!generating && !lastResult && (
                  <div className="rounded-md border border-dashed border-border/60 bg-background/30 py-10 text-center text-sm text-muted-foreground">
                    生成的图片将显示在这里
                  </div>
                )}
                {!generating && lastResult && lastResult.images?.length > 0 && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {lastResult.images.map((url, i) => (
                      <div
                        key={`${url}_${i}`}
                        className="group overflow-hidden rounded-lg border border-border/60 bg-muted/30"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={url}
                          alt={`生成图 ${i + 1}`}
                          className="aspect-square w-full object-cover"
                        />
                        <div className="flex items-center justify-between border-t border-border/60 px-2 py-1.5 text-xs">
                          <span className="text-muted-foreground truncate">
                            #{i + 1} · {lastResult.model_key}
                          </span>
                          <div className="flex items-center gap-1">
                            <Button
                              size="sm"
                              variant="ghost"
                              className="h-7 px-2 text-xs"
                              onClick={() => window.open(buildEditorUrl(url), "_blank", "noopener,noreferrer")}
                              title="在图片编辑器中打开"
                            >
                              <PenSquare className="mr-1 h-3 w-3" />编辑
                            </Button>
                            <a
                              href={url}
                              download={`prism-gen-${i + 1}.png`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center rounded-md hover:bg-accent/60 px-2 py-1.5 text-xs"
                              title="下载"
                            >
                              <Download className="h-3 w-3" />
                            </a>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {!generating && lastResult && lastResult.points && (
                  <div className="flex items-center justify-between rounded-md border border-border/60 bg-background/40 px-3 py-2 text-xs">
                    <span className="text-muted-foreground">
                      本次消耗：{lastResult.points.total} 积分
                      <span className="ml-1 opacity-70">（status={lastResult.points.status}）</span>
                    </span>
                    <span className="text-muted-foreground">
                      aspect: {lastResult.aspect_ratio ?? "-"} · count: {lastResult.count ?? lastResult.images?.length ?? 0}
                    </span>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-card/60">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm flex items-center gap-2">
                    <ImageIcon className="h-4 w-4 text-primary" />生成记录
                    <Badge variant="outline" className="text-xs">
                      {recordsTotal} 条
                    </Badge>
                  </CardTitle>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void loadRecords()}
                    disabled={recordsLoading}
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${recordsLoading ? "animate-spin" : ""}`} />
                  </Button>
                </div>
                <CardDescription>
                  来自 <code>/api/v1/ai-design/records</code> · 最近 10 条
                </CardDescription>
              </CardHeader>
              <CardContent>
                {recordsLoading && records.length === 0 ? (
                  <div className="py-6 text-center text-sm text-muted-foreground">加载中…</div>
                ) : records.length === 0 ? (
                  <div className="py-6 text-center text-sm text-muted-foreground">
                    暂无生成记录，点击右上角刷新或先完成一次生成。
                  </div>
                ) : (
                  <div className="grid gap-2">
                    {records.map((r, i) => {
                      const n = normalizeRecord(r)
                      return (
                        <div
                          key={n.id || `${n.taskId}_${i}`}
                          className="flex items-center gap-3 rounded-md border border-border/60 bg-background/40 p-2"
                        >
                          <div className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded border border-border/60 bg-muted/30">
                            {n.images.length > 0 ? (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img src={n.images[0]} alt="" className="h-full w-full object-cover" />
                            ) : (
                              <ImageIcon className="h-4 w-4 text-muted-foreground" />
                            )}
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 text-xs">
                              <Badge variant="outline" className="text-[10px]">{n.modelKey}</Badge>
                              <span className="text-muted-foreground">{n.aspectRatio}</span>
                              <span className="text-muted-foreground">× {n.count || n.images.length}</span>
                              {n.agentId && (
                                <span className="text-muted-foreground flex items-center gap-1">
                                  <Bot className="h-3 w-3" />{n.agentId.slice(0, 8)}
                                </span>
                              )}
                              {n.createdAt > 0 && (
                                <span className="text-muted-foreground">
                                  · {new Date(n.createdAt * 1000).toLocaleString()}
                                </span>
                              )}
                            </div>
                            <p className="mt-1 truncate text-sm text-foreground">{n.prompt}</p>
                          </div>
                          {n.images.length > 0 && (
                            <Button
                              size="sm"
                              variant="outline"
                              className="h-8 shrink-0"
                              onClick={() => {
                                setLastResult({
                                  task_id: n.taskId,
                                  model_key: n.modelKey,
                                  aspect_ratio: n.aspectRatio,
                                  count: n.count || n.images.length,
                                  images: n.images,
                                  agent_id: n.agentId,
                                  points: n.pointsTotal ? { unit: AI_IMAGE_UNIT_POINTS, total: n.pointsTotal, status: "consumed" } : undefined,
                                })
                              }}
                              title="重新查看这条记录"
                            >
                              <Plus className="h-3.5 w-3.5" />查看
                            </Button>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )}
              </CardContent>
            </Card>

            {activeAgent && (
              <div className="flex items-center justify-between rounded-md border border-primary/30 bg-primary/5 px-3 py-2 text-xs text-primary/90">
                <span className="flex items-center gap-1.5">
                  <Sparkles className="h-3.5 w-3.5" />
                  已选智能体：<span className="font-medium">{activeAgent.name}</span>
                  <span className="opacity-70">（style_prompt 将作为风格信号）</span>
                </span>
                <span className="text-muted-foreground">{activeAgent.style_tokens} tok</span>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
