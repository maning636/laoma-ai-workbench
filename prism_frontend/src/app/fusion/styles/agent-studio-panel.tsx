"use client"

import { useEffect, useState } from "react"
import {
  Bot, RefreshCw, Loader2, Sparkles, Trash2, Plus, Save, Wand2,
} from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Input } from "@/components/ui/input"
import {
  type AgentPublic,
  type AgentQuota,
  buildCreatePayload,
  validateAgentForm,
  quotaUI,
  summarizeStylePrompt,
  EMPTY_FORM,
  AGENT_LIMITS,
  type CreateAgentFormState,
} from "@/lib/agent-studio"
import { API_ENDPOINTS } from "@/lib/env"
import { cloudAuth } from "@/lib/cloud-auth"

const LIST_URL = `${API_ENDPOINTS.base}/api/v1/ai-design/agents`
const QUOTA_URL = `${LIST_URL}/quota`
const CREATE_URL = LIST_URL
const DETAIL_URL = (id: string) => `${LIST_URL}/${id}`
const DELETE_URL = (id: string) => `${LIST_URL}/${id}`

/**
 * M2 hardening：所有 agent 端点都需要 Authorization: Bearer <JWT>。
 * 这里统一从 cloudAuth 拉 access token 注入 fetch header；无 token 时后端会 401，
 * UI 层不隐藏错误，让用户看到"未登录"提示。
 */
async function authFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const token = await cloudAuth.getAccessToken()
  const headers = new Headers(init.headers)
  if (token) headers.set("Authorization", `Bearer ${token}`)
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json")
  }
  return fetch(url, { ...init, headers })
}

export function AgentStudioPanel() {
  const [agents, setAgents] = useState<AgentPublic[]>([])
  const [quota, setQuota] = useState<AgentQuota | null>(null)
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState<CreateAgentFormState>(EMPTY_FORM)
  const [showForm, setShowForm] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [trainingMsg, setTrainingMsg] = useState("")
  const [errors, setErrors] = useState<Partial<Record<keyof CreateAgentFormState, string>>>({})
  const [showDetail, setShowDetail] = useState<string | null>(null)
  const [unauthed, setUnauthed] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [listRes, quotaRes] = await Promise.all([
        authFetch(LIST_URL),
        authFetch(QUOTA_URL),
      ])
      // M2 hardening：所有 agent 端点都需要 JWT 鉴权；未登录时展示提示
      if (listRes.status === 401 || quotaRes.status === 401) {
        setUnauthed(true)
        setAgents([])
        setQuota(null)
        return
      }
      setUnauthed(false)
      if (listRes.ok) {
        const d = await listRes.json()
        setAgents(d.agents || [])
      }
      if (quotaRes.ok) {
        setQuota(await quotaRes.json())
      }
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void load() }, [])

  const q = quotaUI(quota)

  const onSubmit = async () => {
    const v = validateAgentForm(form)
    if (!v.ok) {
      setErrors(v.errors)
      return
    }
    setErrors({})
    const payload = buildCreatePayload(form)
    if (!payload) {
      setErrors({ sample_contents: "请至少填写一条样例内容" })
      return
    }

    setSubmitting(true)
    setTrainingMsg("训练中（调云端 LLM 抽取风格特征）…")
    try {
      const r = await authFetch(CREATE_URL, {
        method: "POST",
        body: JSON.stringify(payload),
      })
      const data = await r.json()
      if (!r.ok) {
        const detail = data?.detail || data
        const msg = typeof detail === "string"
          ? detail
          : detail?.message || detail?.code || "创建失败"
        setTrainingMsg(`训练失败：${msg}`)
        return
      }
      setTrainingMsg("训练完成 ✅")
      setForm(EMPTY_FORM)
      setShowForm(false)
      await load()
    } catch (e) {
      setTrainingMsg(`训练失败：${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSubmitting(false)
    }
  }

  const onDelete = async (id: string) => {
    if (!confirm("确认删除该智能体？（会释放配额）")) return
    await fetch(DELETE_URL(id), { method: "DELETE" })
    if (showDetail === id) setShowDetail(null)
    await load()
  }

  return (
    <Card className="border-primary/40">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" />AI Agent Studio
            <Badge variant="outline" className="text-xs">M2 · 智能体风格训练</Badge>
          </CardTitle>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs">
              配额 {q.label}
            </Badge>
            <Button size="sm" variant="ghost" onClick={() => void load()} disabled={loading}>
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setErrors({})
                setTrainingMsg("")
                setShowForm((v) => !v)
              }}
              disabled={q.disabled}
              title={q.disabled ? "已达配额上限" : "新建智能体"}
            >
              <Plus className="h-4 w-4 mr-1" />新建
            </Button>
          </div>
        </div>
        {q.showUpgrade && (
          <div className="text-xs text-amber-600 dark:text-amber-400">
            已达配额上限，可加微信开通解锁更多智能体。
          </div>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {unauthed && (
          <div className="rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600 dark:text-amber-400">
            请先登录以管理你的智能体。M2 智能体接口已启用 JWT 鉴权。
            <a
              href="/login"
              className="ml-2 underline underline-offset-2 hover:text-amber-500"
            >
              前往登录 →
            </a>
          </div>
        )}
        {showForm && (
          <div className="rounded-md border bg-muted/20 p-3 space-y-2">
            <div className="grid gap-2 md:grid-cols-2">
              <div className="space-y-1">
                <label className="text-xs">名称 <span className="text-red-500">* 必填</span></label>
                <Input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  maxLength={AGENT_LIMITS.nameMax}
                  placeholder="例如：冷色调极简海报"
                />
                {errors.name && <div className="text-xs text-red-500">{errors.name}</div>}
              </div>
              <div className="space-y-1">
                <label className="text-xs">描述（≤{AGENT_LIMITS.descriptionMax} 字）</label>
                <Input
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  maxLength={AGENT_LIMITS.descriptionMax}
                  placeholder="一句话说明这个智能体的用途"
                />
                {errors.description && <div className="text-xs text-red-500">{errors.description}</div>}
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-xs">样例内容 <span className="text-red-500">* 必填</span>（每行一条，参考澜途「优秀轮播图/详情图」）</label>
              <Textarea
                value={form.sample_contents}
                onChange={(e) => setForm({ ...form, sample_contents: e.target.value })}
                placeholder={"标题：新品上市\n正文：三款夏日新品已上架\n\n标题：夏末狂欢\n正文：全场 8 折起"}
                className="min-h-[120px]"
              />
              {errors.sample_contents && <div className="text-xs text-red-500">{errors.sample_contents}</div>}
            </div>
            <div className="space-y-1">
              <label className="text-xs">设计原则（≤{AGENT_LIMITS.designPrinciplesMax} 字，选填）</label>
              <Textarea
                value={form.design_principles}
                onChange={(e) => setForm({ ...form, design_principles: e.target.value })}
                placeholder="主色控制 / 文案字数 / 首屏要求 …"
                className="min-h-[80px]"
              />
              {errors.design_principles && <div className="text-xs text-red-500">{errors.design_principles}</div>}
            </div>
            <div className="flex items-center gap-2 pt-1">
              <Button onClick={() => void onSubmit()} disabled={submitting}>
                <Wand2 className="h-4 w-4 mr-2" />训练并创建
              </Button>
              {submitting && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
              {trainingMsg && (
                <span className="text-xs text-muted-foreground">{trainingMsg}</span>
              )}
            </div>
          </div>
        )}

        {agents.length === 0 && !loading ? (
          <div className="text-center py-6 text-sm text-muted-foreground">
            还没有智能体。点击“新建”训练第一个风格智能体。
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {agents.map((a) => (
              <div key={a.id} className="rounded-md border p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 min-w-0">
                    <Sparkles className="h-4 w-4 text-primary shrink-0" />
                    <span className="font-medium truncate">{a.name}</span>
                  </div>
                  <Badge variant="outline" className="text-xs shrink-0">
                    {a.style_tokens} tok
                  </Badge>
                </div>
                {a.description && (
                  <div className="text-xs text-muted-foreground">{a.description}</div>
                )}
                <div className="text-xs text-muted-foreground">
                  <span className="font-medium text-foreground">风格摘要：</span>
                  {summarizeStylePrompt(a.style_prompt, 100)}
                </div>
                <div className="text-xs text-muted-foreground">
                  样例 {a.sample_contents.length} 条 · 更新于 {new Date(a.updated_at * 1000).toLocaleString()}
                </div>
                <div className="flex items-center gap-2 pt-1">
                  <Button
                    size="sm" variant="ghost"
                    onClick={() => setShowDetail(showDetail === a.id ? null : a.id)}
                  >
                    {showDetail === a.id ? "收起" : "查看 style_prompt"}
                  </Button>
                  <Button
                    size="sm" variant="ghost"
                    className="text-red-600 hover:text-red-700"
                    onClick={() => void onDelete(a.id)}
                  >
                    <Trash2 className="h-3 w-3 mr-1" />删除
                  </Button>
                </div>
                {showDetail === a.id && (
                  <pre className="text-xs bg-muted/40 border rounded p-2 whitespace-pre-wrap">
                    {a.style_prompt || "（空 style_prompt）"}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default AgentStudioPanel
