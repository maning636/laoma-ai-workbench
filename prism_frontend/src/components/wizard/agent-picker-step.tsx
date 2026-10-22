/**
 * M4 hardening · AI 生图场景智能体选择器（接入 M2 agent studio）。
 *
 * 行为：
 *   - 组件挂载时调 `GET /api/v1/ai-design/agents` + `/quota`
 *   - 展示 shadcn `Select` 下拉；默认"不使用智能体"
 *   - 选中值写入 module-scope cache，Wizard 组件因 Suspense fallback 切换
 *     步骤后重挂载时能从 cache 恢复上次选择
 *   - 401（M2 hardening 后需要 JWT）→ 显示未登录提示
 */
"use client"

import { useEffect, useState } from "react"
import { Bot, Info, Loader2, LogIn, Sparkles, Crown } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

import { API_ENDPOINTS } from "@/lib/env"
import { cloudAuth } from "@/lib/cloud-auth"
import {
  buildPlanBadgeView,
  normalizeFlags,
  type FeatureFlagsResponse,
} from "@/lib/plan-flags"

const AGENTS_LIST_URL = `${API_ENDPOINTS.base}/api/v1/ai-design/agents`
const AGENTS_QUOTA_URL = `${AGENTS_LIST_URL}/quota`
/** 最终生效 flag（注册码 ∩ 云端订阅）——本地后端算好 */
const FLAGS_URL = `${API_ENDPOINTS.base}/api/v1/license/effective-flags`

export const NO_AGENT_VALUE = "__none__"

/**
 * 模块级跨步骤缓存：Wizard 里 useReducer + Suspense fallback 会因步骤切换而
 * remount step.render；用模块级 Map 存住上次选中值。
 */
const _agentIdCache = new Map<string, string>()

async function authFetch(url: string): Promise<Response> {
  const token = await cloudAuth.getAccessToken()
  const headers = new Headers()
  if (token) headers.set("Authorization", `Bearer ${token}`)
  return fetch(url, { headers })
}

function normalizeAgent(a: Record<string, unknown>) {
  return {
    id: String(a.id ?? ""),
    name: String(a.name ?? ""),
    description: String(a.description ?? ""),
    style_prompt: String(a.style_prompt ?? ""),
    style_tokens: Number(a.style_tokens ?? 0),
    updated_at: Number(a.updated_at ?? 0),
  }
}

export function AgentPickerStep() {
  const [agents, setAgents] = useState<ReturnType<typeof normalizeAgent>[]>([])
  const [quota, setQuota] = useState<{ limit: number; used: number } | null>(null)
  const [flags, setFlags] = useState<FeatureFlagsResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [unauthed, setUnauthed] = useState(false)
  const [selectedId, setSelectedId] = useState<string>(
    _agentIdCache.get(AGENTS_LIST_URL) ?? NO_AGENT_VALUE,
  )

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [listRes, quotaRes] = await Promise.all([
          authFetch(AGENTS_LIST_URL),
          authFetch(AGENTS_QUOTA_URL),
        ])
        if (listRes.status === 401 || quotaRes.status === 401) {
          if (!cancelled) {
            setUnauthed(true)
            setAgents([])
            setQuota(null)
          }
          return
        }
        if (!cancelled) setUnauthed(false)
        if (listRes.ok) {
          const d = await listRes.json()
          if (!cancelled) {
            setAgents(
              ((d.agents ?? []) as Record<string, unknown>[]).map(normalizeAgent),
            )
          }
        }
        if (quotaRes.ok) {
          const q = await quotaRes.json()
          if (!cancelled) setQuota(q)
        }
      } catch (e) {
        console.error(e)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [])

  // 并行拉取最终生效的 feature flags（用于判断 agent_quota=0 显示升级提示）
  // 读**本地后端**的 `/api/v1/license/effective-flags`（= 注册码 ∩ 云端订阅 的最终交集），
  // 而不是直接读云端 —— 否则有注册码但未同步云端的用户会被误判为限制功能版。
  // 本地后端不可达 / 未登录 → 默认 Community + agent_quota=0（不阻断 UI）
  useEffect(() => {
    let cancelled = false
    async function loadFlags() {
      try {
        const token = await cloudAuth.getAccessToken()
        const headers = new Headers()
        if (token) headers.set("Authorization", `Bearer ${token}`)
        const r = await fetch(FLAGS_URL, { headers, cache: "no-store" })
        if (cancelled) return
        if (r.ok) {
          const data = (await r.json()) as FeatureFlagsResponse
          setFlags(normalizeFlags(data))
        } else {
          // 本地后端不可达/未登录：回落 Community + agent_quota=0
          setFlags(normalizeFlags({ plan: "community", flags: {} }))
        }
      } catch (e) {
        if (!cancelled) setFlags(normalizeFlags({ plan: "community", flags: {} }))
      }
    }
    void loadFlags()
    return () => {
      cancelled = true
    }
  }, [])

  const handleSelect = (value: string) => {
    setSelectedId(value)
    _agentIdCache.set(AGENTS_LIST_URL, value)
    window.dispatchEvent(
      new CustomEvent("prism-wizard:agent-selected", {
        detail: { agent_id: value === NO_AGENT_VALUE ? "" : value },
      }),
    )
  }

  const selectedAgent =
    selectedId === NO_AGENT_VALUE
      ? null
      : agents.find((a) => a.id === selectedId) ?? null

  const view = flags ? buildPlanBadgeView(flags) : null
  // Community + agent_quota=0 → 明确禁用智能体选择，仅显示升级 Pro 提示
  const agentLocked =
    !unauthed &&
    flags !== null &&
    flags.plan !== "pro" &&
    Number(flags.flags.agent_quota ?? 0) === 0

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border/60 bg-background/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" />
            <p className="text-sm font-semibold text-foreground">
              选择风格智能体（可选）
            </p>
          </div>
          {quota && (
            <Badge variant="secondary" className="text-xs">
              配额 {quota.used}/{quota.limit}
            </Badge>
          )}
          <Button
            size="sm"
            variant="ghost"
            className="text-xs gap-1"
            onClick={() => {
              setLoading(true)
              void (async () => {
                try {
                  const [listRes, quotaRes] = await Promise.all([
                    authFetch(AGENTS_LIST_URL),
                    authFetch(AGENTS_QUOTA_URL),
                  ])
                  if (listRes.status === 401) {
                    setUnauthed(true)
                    return
                  }
                  if (listRes.ok) {
                    const d = await listRes.json()
                    setAgents(
                      ((d.agents ?? []) as Record<string, unknown>[]).map(
                        normalizeAgent,
                      ),
                    )
                  }
                  if (quotaRes.ok) setQuota(await quotaRes.json())
                } finally {
                  setLoading(false)
                }
              })()
            }}
          >
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            刷新
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          选中智能体后，AI 生图会把 style_prompt 拼到用户 prompt 头部，输出更贴合你的
          品牌风格。可跳过此步骤直接使用默认生图流程。
        </p>
      </div>

      {unauthed ? (
        <div className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600 dark:text-amber-400">
          <LogIn className="h-3.5 w-3.5 shrink-0" />
          <span>请先登录以使用智能体风格训练（M2 · Agent Studio）。</span>
          <a href="/login" className="underline underline-offset-2">
            前往登录 →
          </a>
        </div>
      ) : loading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
          加载中…
        </div>
      ) : agentLocked ? (
        <div className="flex flex-col gap-2 rounded-md border border-primary/40 bg-primary/5 p-3">
          <div className="flex items-center gap-2 text-xs text-primary">
            <Crown className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">
              当前为限制功能版，智能体风格训练为完整版功能。
            </span>
          </div>
          <div className="text-xs text-muted-foreground">
            限制功能版智能体配额为 0，无法创建或使用风格智能体。加微信开通可解锁
            {view ? ` ${view.agentLabel} 个智能体 ` : " 更多智能体 "}
            并支持云端 LLM 风格训练。
          </div>
          <a
            href={view?.upgradeUrl || "/settings#contact"}
            className="mt-1 inline-flex w-fit items-center gap-1.5 rounded-lg border border-primary/40 bg-primary/10 px-2.5 py-1.5 text-xs font-medium text-primary hover:bg-primary hover:text-background transition-colors"
          >
            <Crown className="h-3.5 w-3.5" />
            加微信开通解锁智能体
          </a>
        </div>
      ) : (
        <>
          <div className="grid gap-2">
            <Select value={selectedId} onValueChange={handleSelect}>
              <SelectTrigger className="h-10">
                <SelectValue placeholder="选择智能体（或跳过）" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_AGENT_VALUE}>
                  不使用智能体（默认）
                </SelectItem>
                {agents.length === 0 && (
                  <SelectItem value="__empty__" disabled>
                    （暂无智能体，前往 AI Agent Studio 创建）
                  </SelectItem>
                )}
                {agents.map((a) => (
                  <SelectItem key={a.id} value={a.id}>
                    <span className="flex items-center gap-1.5">
                      <Sparkles className="h-3 w-3 text-primary" />
                      {a.name}
                      {a.description && (
                        <span className="text-muted-foreground">
                          · {a.description}
                        </span>
                      )}
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {selectedAgent && (
              <div className="rounded-md border border-border/60 bg-background/40 p-3 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-foreground">
                    {selectedAgent.name}
                  </span>
                  <Badge variant="outline" className="text-xs">
                    {selectedAgent.style_tokens} tok
                  </Badge>
                </div>
                {selectedAgent.description && (
                  <p className="text-xs text-muted-foreground">
                    {selectedAgent.description}
                  </p>
                )}
                <div className="flex items-start gap-1 text-xs text-muted-foreground">
                  <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
                  <span className="line-clamp-3">
                    {selectedAgent.style_prompt || "（无 style_prompt）"}
                  </span>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}
