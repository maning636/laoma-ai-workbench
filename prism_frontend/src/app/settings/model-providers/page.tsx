"use client"

import { useCallback, useEffect, useState } from "react"
import Link from "next/link"
import {
  AlertTriangle,
  ArrowLeft,
  Boxes,
  Download,
  Loader2,
  Pencil,
  Plug,
  Plus,
  RefreshCw,
  TestTube2,
  Trash2,
} from "lucide-react"
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/use-toast"
import { API_ENDPOINTS } from "@/lib/env"

// ---------- 类型定义 ----------

export type ProviderRow = {
  id: number
  name: string
  base_url?: string | null
  // 后端 _row_to_provider 输出字段名 api_key（值已被 _mask_key 打码）
  api_key?: string | null
  enabled: boolean
  remark?: string | null
  // 后端未缓存模型时为 null；仅"拉取模型"成功后才是 string[]
  available_models: string[] | null
  created_at?: string
  updated_at?: string
}

export type ProviderDraft = {
  id?: number
  name: string
  base_url: string
  api_key: string
  remark: string
}

export type TestResult = {
  ok: boolean
  latency_ms?: number | null
  model_count?: number | null
  error?: string | null
}

export type DeleteRefs = {
  detail?: {
    references?: Array<{ service_type: string; provider?: string }>
    message?: string
  }
  message?: string
}

// service_type 枚举：与后端 ai_model_configs 里已存在的通道对齐；
// 后端 apply-to 不校验枚举、按字符串 upsert，此处前端枚举仅为下拉选项。
const SERVICE_TYPES: Array<{ value: string; label: string; description: string }> = [
  { value: "chat", label: "chat（对话 / 标题生成）", description: "对应 Hermes 主通道与 chat 服务" },
  { value: "whisper", label: "whisper（语音识别）", description: "对应 transcribe 语音转写通道" },
  { value: "cover_generation", label: "cover_generation（封面图）", description: "image 通道（未开放前也支持写入）" },
  { value: "video_generation", label: "video_generation（视频生成）", description: "video 通道（预留）" },
  { value: "speech_recognition", label: "speech_recognition（语音识别备份）", description: "与 whisper 并存的旧别名" },
]

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim())
}

function validateDraft(draft: ProviderDraft, existing: ProviderRow[]): string | null {
  if (!draft.name.trim()) return "名称必填"
  const duplicate = existing.some((row) => row.id !== draft.id && row.name === draft.name.trim())
  if (duplicate) return "名称重复：已存在同名供应商"
  if (draft.base_url.trim() && !isHttpUrl(draft.base_url)) {
    return "BaseURL 必须以 http:// 或 https:// 开头"
  }
  return null
}

// ---------- 页面 ----------

export default function ModelProvidersPage() {
  const { toast } = useToast()
  const [rows, setRows] = useState<ProviderRow[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // 添加 / 编辑
  const [formOpen, setFormOpen] = useState(false)
  const [formDraft, setFormDraft] = useState<ProviderDraft>({ name: "", base_url: "", api_key: "", remark: "" })
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // 应用到通道
  const [applyOpen, setApplyOpen] = useState(false)
  const [applyTarget, setApplyTarget] = useState<ProviderRow | null>(null)
  const [applyService, setApplyService] = useState<string>("chat")
  const [applyModel, setApplyModel] = useState<string>("")
  const [applying, setApplying] = useState(false)

  // 删除
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<ProviderRow | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteRefs, setDeleteRefs] = useState<DeleteRefs | null>(null)

  // 每行独立状态：测试连接 / 拉取模型 / 启用切换
  const [testStates, setTestStates] = useState<Record<number, { loading: boolean; result: TestResult | null }>>({})
  const [modelsStates, setModelsStates] = useState<Record<number, boolean>>({})

  const loadList = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const res = await fetch(`${API_ENDPOINTS.aiProviders}?_=${Date.now()}`, { cache: "no-store" })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(payload?.detail || `加载失败（HTTP ${res.status}）`)
      }
      const data = Array.isArray(payload?.data) ? (payload.data as ProviderRow[]) : []
      setRows(data)
    } catch (error) {
      setLoadError(getErrorMessage(error) || "网络错误")
      toast({
        title: "供应商列表加载失败",
        description: getErrorMessage(error),
        variant: "destructive",
        dedupeKey: "providers-load-failed",
      })
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void loadList()
  }, [loadList])

  const openAdd = () => {
    setFormDraft({ name: "", base_url: "", api_key: "", remark: "" })
    setFormError(null)
    setFormOpen(true)
  }

  const openEdit = (row: ProviderRow) => {
    setFormDraft({
      id: row.id,
      name: row.name,
      base_url: row.base_url || "",
      // api_key 走 masked 值作为占位；用户不改则提交时留空表示"不改"
      api_key: "",
      remark: row.remark || "",
    })
    setFormError(null)
    setFormOpen(true)
  }

  const submitForm = async () => {
    const validation = validateDraft(formDraft, rows)
    if (validation) {
      setFormError(validation)
      return
    }
    setSubmitting(true)
    try {
      const isEdit = typeof formDraft.id === "number"
      const url = isEdit
        ? `${API_ENDPOINTS.aiProviders}/${formDraft.id}`
        : API_ENDPOINTS.aiProviders
      const body: Record<string, string | boolean> = {
        name: formDraft.name.trim(),
        base_url: formDraft.base_url.trim(),
        remark: formDraft.remark.trim(),
      }
      // 创建时默认启用；编辑时不送 enabled，让后端保留原值（避免"停用→编辑"被静默重新启用）
      if (isEdit) {
        if (formDraft.api_key.trim()) body.api_key = formDraft.api_key.trim()
      } else {
        body.api_key = formDraft.api_key.trim()
        body.enabled = true
      }
      const res = await fetch(url, {
        method: isEdit ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(payload?.detail || (isEdit ? "更新失败" : "创建失败"))
      }
      setFormOpen(false)
      toast({
        title: isEdit ? "供应商已更新" : "供应商已添加",
        description: `「${body.name}」${isEdit ? "保存成功" : "已创建"}`,
        dedupeKey: isEdit ? "providers-update-ok" : "providers-create-ok",
      })
      await loadList()
    } catch (error) {
      setFormError(getErrorMessage(error))
      toast({
        title: "操作失败",
        description: getErrorMessage(error),
        variant: "destructive",
        dedupeKey: "providers-form-failed",
      })
    } finally {
      setSubmitting(false)
    }
  }

  const toggleEnabled = async (row: ProviderRow, enabled: boolean) => {
    // 乐观更新
    setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, enabled } : r)))
    try {
      const res = await fetch(`${API_ENDPOINTS.aiProviders}/${row.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      })
      if (!res.ok) {
        const payload = await res.json().catch(() => ({}))
        throw new Error(payload?.detail || `切换失败（HTTP ${res.status}）`)
      }
      toast({
        title: enabled ? "已启用供应商" : "已停用供应商",
        description: `「${row.name}」状态已更新`,
        dedupeKey: `providers-toggle-${row.id}`,
      })
    } catch (error) {
      // 回滚
      setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, enabled: !enabled } : r)))
      toast({
        title: "切换失败",
        description: getErrorMessage(error),
        variant: "destructive",
        dedupeKey: `providers-toggle-${row.id}`,
      })
    }
  }

  const runTestConnection = async (row: ProviderRow) => {
    setTestStates((prev) => ({ ...prev, [row.id]: { loading: true, result: null } }))
    try {
      const res = await fetch(`${API_ENDPOINTS.aiProviders}/${row.id}/test-connection`, { method: "POST" })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(payload?.detail || `测试失败（HTTP ${res.status}）`)
      }
      const result: TestResult = {
        ok: !!payload?.ok,
        latency_ms: payload?.latency_ms,
        model_count: payload?.model_count,
        error: payload?.error,
      }
      setTestStates((prev) => ({ ...prev, [row.id]: { loading: false, result } }))
    } catch (error) {
      setTestStates((prev) => ({
        ...prev,
        [row.id]: { loading: false, result: { ok: false, error: getErrorMessage(error) } },
      }))
    }
  }

  const fetchModels = async (row: ProviderRow) => {
    setModelsStates((prev) => ({ ...prev, [row.id]: true }))
    try {
      const res = await fetch(`${API_ENDPOINTS.aiProviders}/${row.id}/models`, { cache: "no-store" })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(payload?.detail || payload?.message || `拉取模型失败（HTTP ${res.status}）`)
      }
      const models: string[] = Array.isArray(payload?.data?.models)
        ? payload.data.models
        : Array.isArray(payload?.models)
          ? payload.models
          : []
      setRows((prev) => prev.map((r) => (r.id === row.id ? { ...r, available_models: models } : r)))
      toast({
        title: "模型列表已更新",
        description: `「${row.name}」共 ${models.length} 个模型`,
        dedupeKey: `providers-models-${row.id}-ok`,
      })
    } catch (error) {
      toast({
        title: "拉取模型失败",
        description: getErrorMessage(error),
        variant: "destructive",
        dedupeKey: `providers-models-${row.id}-failed`,
      })
    } finally {
      setModelsStates((prev) => ({ ...prev, [row.id]: false }))
    }
  }

  const openApply = (row: ProviderRow) => {
    setApplyTarget(row)
    setApplyService("chat")
    setApplyModel(row.available_models?.[0] || "")
    setApplyOpen(true)
  }

  const submitApply = async () => {
    if (!applyTarget) return
    if (!applyModel.trim()) {
      toast({
        title: "请选择模型",
        description: "先选择或输入一个模型名称再提交。",
        variant: "destructive",
        dedupeKey: "providers-apply-empty-model",
      })
      return
    }
    setApplying(true)
    try {
      const res = await fetch(`${API_ENDPOINTS.aiProviders}/${applyTarget.id}/apply-to/${applyService}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_name: applyModel.trim() }),
      })
      const payload = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(payload?.detail || `应用失败（HTTP ${res.status}）`)
      }
      setApplyOpen(false)
      toast({
        title: "已应用到通道",
        description: payload?.message || `「${applyTarget.name}」→ ${applyService}（${applyModel.trim()}）`,
        dedupeKey: `providers-apply-${applyTarget.id}-${applyService}`,
      })
    } catch (error) {
      toast({
        title: "应用失败",
        description: getErrorMessage(error),
        variant: "destructive",
        dedupeKey: `providers-apply-${applyTarget.id}-${applyService}`,
      })
    } finally {
      setApplying(false)
    }
  }

  const openDelete = (row: ProviderRow) => {
    setDeleteTarget(row)
    setDeleteRefs(null)
    setDeleteOpen(true)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    setDeleteRefs(null)
    try {
      const res = await fetch(`${API_ENDPOINTS.aiProviders}/${deleteTarget.id}`, { method: "DELETE" })
      const payload = await res.json().catch(() => ({}))
      if (res.status === 409) {
        const refs = (payload?.detail?.references || payload?.references) as
          | Array<{ service_type: string; provider?: string }>
          | undefined
        setDeleteRefs({ detail: { references: refs } })
        return
      }
      if (!res.ok) {
        throw new Error(payload?.detail || `删除失败（HTTP ${res.status}）`)
      }
      setDeleteOpen(false)
      setRows((prev) => prev.filter((r) => r.id !== deleteTarget.id))
      toast({
        title: "已删除供应商",
        description: `「${deleteTarget.name}」已从注册表移除`,
        dedupeKey: `providers-delete-${deleteTarget.id}-ok`,
      })
    } catch (error) {
      toast({
        title: "删除失败",
        description: getErrorMessage(error),
        variant: "destructive",
        dedupeKey: `providers-delete-${deleteTarget.id}-failed`,
      })
    } finally {
      setDeleting(false)
    }
  }

  const deleteRefsList = Array.isArray(deleteRefs?.detail?.references)
    ? deleteRefs.detail.references
    : []

  return (
    <div className="mx-auto max-w-[1440px] space-y-5 px-4 py-4 md:px-6 md:py-5">
      {/* 页头 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link
            href="/settings"
            className="inline-flex items-center gap-1.5 rounded-lg border border-border/70 bg-card px-2.5 py-1.5 text-xs text-foreground hover:bg-accent/40"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            返回设置
          </Link>
          <div className="flex items-center gap-2">
            <Boxes className="h-5 w-5 text-foreground/70" />
            <div>
              <div className="text-sm font-medium text-foreground">模型供应商管理</div>
              <div className="text-xs text-muted-foreground">OpenRouter / one-api 风格注册表</div>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            className="border-border/70 bg-card text-foreground hover:bg-accent/40"
            onClick={() => void loadList()}
            disabled={loading}
          >
            {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-2 h-4 w-4" />}
            刷新
          </Button>
          <Button
            className="border-border/80 bg-popover text-foreground hover:bg-accent/50"
            onClick={openAdd}
            disabled={submitting}
          >
            <Plus className="mr-2 h-4 w-4" />
            添加供应商
          </Button>
        </div>
      </div>

      {/* 状态区 */}
      {loading ? (
        <div className="flex items-center justify-center rounded-2xl border border-border/70 bg-card py-16">
          <Loader2 className="mr-2 h-5 w-5 animate-spin text-muted-foreground" />
          <span className="text-sm text-muted-foreground">正在加载供应商列表…</span>
        </div>
      ) : loadError ? (
        <div className="rounded-2xl border border-dashed border-border/70 bg-card/40 px-5 py-10 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-foreground/50" />
          <div className="mt-3 text-sm font-medium text-foreground">供应商列表加载失败</div>
          <div className="mt-1 text-xs text-muted-foreground">{loadError}</div>
          <Button
            variant="secondary"
            className="mt-4 border-border/70 bg-card text-foreground hover:bg-accent/40"
            onClick={() => void loadList()}
          >
            <RefreshCw className="mr-2 h-4 w-4" />
            重试
          </Button>
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border/70 bg-card/40 px-5 py-10 text-center">
          <Boxes className="mx-auto h-8 w-8 text-foreground/50" />
          <div className="mt-3 text-sm font-medium text-foreground">还没有供应商</div>
          <div className="mt-1 text-xs text-muted-foreground">添加 OpenAI 兼容的推理服务，就能一键应用到各通道。</div>
          <Button
            className="mt-4 border-border/80 bg-popover text-foreground hover:bg-accent/50"
            onClick={openAdd}
          >
            <Plus className="mr-2 h-4 w-4" />
            添加第一个供应商
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          {rows.map((row) => {
            const testState = testStates[row.id]
            const modelsLoading = !!modelsStates[row.id]
            return (
              <Card key={row.id} className="border-border/70 bg-card">
                <CardHeader className="p-4 pb-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <CardTitle className="text-sm font-semibold text-foreground">
                          {row.name}
                        </CardTitle>
                        <Badge
                          variant="outline"
                          className={
                            row.enabled
                              ? "border-border/80 bg-popover text-foreground"
                              : "border-border/70 bg-card text-muted-foreground"
                          }
                        >
                          {row.enabled ? "已启用" : "已停用"}
                        </Badge>
                        <Badge variant="outline" className="border-border/70 bg-card text-muted-foreground">
                          {row.available_models
                            ? `${row.available_models.length} 个模型`
                            : "—"}
                        </Badge>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        BaseURL：
                        <span className="break-all font-mono text-foreground/80">
                          {row.base_url || "-"}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        API Key：
                        <span className="font-mono text-foreground/80">{row.api_key || "（未填写）"}</span>
                        {row.remark ? <span className="ml-3 text-muted-foreground">备注：{row.remark}</span> : null}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">启用</span>
                      <Switch
                        checked={row.enabled}
                        onCheckedChange={(checked) => void toggleEnabled(row, checked)}
                        aria-label={`启用 ${row.name}`}
                      />
                    </div>
                  </div>
                </CardHeader>

                <CardContent className="space-y-3 p-4 pt-0">
                  {testState?.loading ? (
                    <div className="flex items-center gap-2 rounded-xl border border-border/70 bg-card px-3 py-2 text-xs text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      正在测试连接…
                    </div>
                  ) : testState?.result ? (
                    <div
                      data-testid={`test-result-${row.id}`}
                      className={[
                        "flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2 text-xs",
                        testState.result.ok
                          ? "border-border/80 bg-popover text-foreground"
                          : "border-border/70 bg-card text-muted-foreground",
                      ].join(" ")}
                    >
                      <span>{testState.result.ok ? "✓" : "✗"}</span>
                      {testState.result.ok ? (
                        <span>
                          {typeof testState.result.latency_ms === "number"
                            ? `${testState.result.latency_ms}ms`
                            : "已连通"}
                          {" · "}
                          {typeof testState.result.model_count === "number"
                            ? `${testState.result.model_count} 个模型`
                            : "模型数未知"}
                        </span>
                      ) : (
                        <span>{testState.result.error || "测试失败"}</span>
                      )}
                    </div>
                  ) : null}

                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      variant="secondary"
                      className="border-border/70 bg-card text-foreground hover:bg-accent/40"
                      onClick={() => void runTestConnection(row)}
                      disabled={testState?.loading}
                    >
                      {testState?.loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <TestTube2 className="mr-2 h-4 w-4" />}
                      测试连接
                    </Button>
                    <Button
                      variant="secondary"
                      className="border-border/70 bg-card text-foreground hover:bg-accent/40"
                      onClick={() => void fetchModels(row)}
                      disabled={modelsLoading}
                    >
                      {modelsLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
                      拉取模型
                    </Button>
                    <Button
                      variant="secondary"
                      className="border-border/70 bg-card text-foreground hover:bg-accent/40"
                      onClick={() => openApply(row)}
                    >
                      <Plug className="mr-2 h-4 w-4" />
                      应用到通道
                    </Button>
                    <Button
                      variant="secondary"
                      className="border-border/70 bg-card text-foreground hover:bg-accent/40"
                      onClick={() => openEdit(row)}
                    >
                      <Pencil className="mr-2 h-4 w-4" />
                      编辑
                    </Button>
                    <Button
                      variant="secondary"
                      className="border-border/70 bg-card text-foreground/70 hover:bg-accent/40"
                      onClick={() => openDelete(row)}
                    >
                      <Trash2 className="mr-2 h-4 w-4" />
                      删除
                    </Button>
                  </div>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}

      {/* 添加 / 编辑 Dialog */}
      <Dialog open={formOpen} onOpenChange={setFormOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{typeof formDraft.id === "number" ? "编辑供应商" : "添加供应商"}</DialogTitle>
            <DialogDescription>
              填写 OpenAI 兼容推理服务的地址和密钥。API Key 仅保存在本机注册表；再次提交时若留空则保持原值不变。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="provider-name">名称（唯一）</Label>
              <Input
                id="provider-name"
                value={formDraft.name}
                onChange={(e) => {
                  setFormDraft((prev) => ({ ...prev, name: e.target.value }))
                  setFormError(null)
                }}
                placeholder="例如 OpenRouter / SiliconFlow / 内部代理"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="provider-base-url">BaseURL</Label>
              <Input
                id="provider-base-url"
                value={formDraft.base_url}
                onChange={(e) => {
                  setFormDraft((prev) => ({ ...prev, base_url: e.target.value }))
                  setFormError(null)
                }}
                placeholder="https://api.example.com/v1"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="provider-api-key">API Key</Label>
              <Input
                id="provider-api-key"
                type="password"
                value={formDraft.api_key}
                onChange={(e) => {
                  setFormDraft((prev) => ({ ...prev, api_key: e.target.value }))
                  setFormError(null)
                }}
                placeholder={
                  typeof formDraft.id === "number"
                    ? "留空表示保持原密钥不变"
                    : "sk-..."
                }
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="provider-remark">备注（可选）</Label>
              <Textarea
                id="provider-remark"
                value={formDraft.remark}
                onChange={(e) => setFormDraft((prev) => ({ ...prev, remark: e.target.value }))}
                placeholder="例如：主账号 / 备用账号"
                rows={2}
              />
            </div>
            {formError ? (
              <div className="rounded-lg border border-dashed border-border/70 bg-card px-3 py-2 text-xs text-muted-foreground">
                {formError}
              </div>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              variant="secondary"
              className="border-border/70 bg-card text-foreground hover:bg-accent/40"
              onClick={() => setFormOpen(false)}
            >
              取消
            </Button>
            <Button
              className="border-border/80 bg-popover text-foreground hover:bg-accent/50"
              onClick={() => void submitForm()}
              disabled={submitting}
            >
              {submitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {typeof formDraft.id === "number" ? "保存修改" : "创建供应商"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 应用到通道 Dialog */}
      <Dialog open={applyOpen} onOpenChange={setApplyOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>
              应用到通道：{applyTarget?.name || ""}
            </DialogTitle>
            <DialogDescription>
              把该供应商的 BaseURL 与 API Key 写入对应通道的模型配置（覆盖原通道配置）。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="apply-service">目标通道</Label>
              <Select
                value={applyService}
                onValueChange={setApplyService}
                disabled={!applyTarget}
              >
                <SelectTrigger id="apply-service" className="border-border/70 bg-card">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {SERVICE_TYPES.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                {SERVICE_TYPES.find((opt) => opt.value === applyService)?.description || ""}
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="apply-model">模型名称</Label>
              <Input
                id="apply-model"
                value={applyModel}
                onChange={(e) => setApplyModel(e.target.value)}
                placeholder={
                  applyTarget?.available_models && applyTarget.available_models.length > 0
                    ? "从下拉选择或手输"
                    : "先点「拉取模型」自动填充；也可手输模型名"
                }
                list={
                  applyTarget?.available_models && applyTarget.available_models.length > 0
                    ? `models-${applyTarget.id}`
                    : undefined
                }
              />
              {applyTarget?.available_models && applyTarget.available_models.length > 0 ? (
                <datalist id={`models-${applyTarget.id}`}>
                  {applyTarget.available_models.map((m) => (
                    <option key={m} value={m} />
                  ))}
                </datalist>
              ) : null}
              <div className="flex flex-wrap gap-1.5">
                {(applyTarget?.available_models || []).slice(0, 6).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setApplyModel(m)}
                    className="rounded-full border border-border/70 bg-card px-2 py-0.5 text-[11px] text-foreground/80 hover:bg-accent/40"
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="secondary"
              className="border-border/70 bg-card text-foreground hover:bg-accent/40"
              onClick={() => setApplyOpen(false)}
            >
              取消
            </Button>
            <Button
              className="border-border/80 bg-popover text-foreground hover:bg-accent/50"
              onClick={() => void submitApply()}
              disabled={applying || !applyTarget || !applyModel.trim()}
            >
              {applying ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Plug className="mr-2 h-4 w-4" />}
              应用
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 删除确认 Dialog */}
      <AlertDialog open={deleteOpen} onOpenChange={setDeleteOpen}>
        <AlertDialogContent className="border-border/70 bg-card">
          <AlertDialogHeader>
            <AlertDialogTitle>
              删除供应商「{deleteTarget?.name || ""}」？
            </AlertDialogTitle>
            <AlertDialogDescription>
              {deleteRefsList.length > 0 ? (
                <span className="block space-y-1.5">
                  <span className="flex items-center gap-1.5 font-medium text-foreground">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    以下通道正在引用该供应商，请先在这些通道里手动解除：
                  </span>
                  <span className="flex flex-wrap gap-1.5 pt-1">
                    {deleteRefsList.map((ref, idx) => (
                      <span
                        key={`${ref.service_type}-${idx}`}
                        className="inline-flex items-center gap-1 rounded-md border border-border/70 bg-card px-2 py-0.5 text-xs text-foreground"
                      >
                        <span className="font-mono">{ref.service_type}</span>
                        {ref.provider ? (
                          <span className="text-muted-foreground">（{ref.provider}）</span>
                        ) : null}
                      </span>
                    ))}
                  </span>
                </span>
              ) : (
                <span>此操作会永久删除该供应商，注册表记录不可恢复。</span>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel className="border-border/70 bg-card text-foreground hover:bg-accent/40">
              取消
            </AlertDialogCancel>
            {/* 用普通 button 而非 AlertDialogAction：409 时 dialog 需要保持打开
                展示被引用通道列表，而 Radix 的 Action 会自动关闭。 */}
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault()
                void confirmDelete()
              }}
              disabled={deleting || deleteRefsList.length > 0}
              className="inline-flex h-10 items-center justify-center rounded-xl bg-destructive px-4 text-sm font-semibold text-foreground transition hover:bg-destructive/90 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50"
            >
              {deleting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Trash2 className="mr-2 h-4 w-4" />}
              {deleteRefsList.length > 0 ? "被引用中" : "确认删除"}
            </button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
