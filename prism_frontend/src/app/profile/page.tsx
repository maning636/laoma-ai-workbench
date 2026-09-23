"use client"

import { useEffect, useMemo, useState } from "react"
import {
  Activity,
  ClipboardCheck,
  ExternalLink,
  Fingerprint,
  Loader2,
  NotebookPen,
  RefreshCw,
  Send,
  ShieldAlert,
  Sparkles,
  Target,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { useToast } from "@/components/ui/use-toast"

interface ProfileForm {
  platforms: string[]
  links: Record<string, string>
  accountStage: string
  direction: string
  reason: string
  goal: string
  formats: string[]
  likes: string
  tone: string
  avoid: string
}

interface ProfileSummary {
  name: string
  baseline: Record<string, string>
  created_at?: string
  updated_at?: string
  filled_dims?: number
  total_dims?: number
}

type ProfileDetail = ProfileSummary & {
  form: ProfileForm
  engine?: string
}

const EMPTY_FORM: ProfileForm = {
  platforms: [],
  links: {},
  accountStage: "",
  direction: "",
  reason: "",
  goal: "",
  formats: [],
  likes: "",
  tone: "",
  avoid: "",
}

const PLATFORM_KEYS = ["抖音", "小红书", "B站", "快手", "视频号", "TikTok", "YouTube"]

const PLATFORMS = ["抖音", "小红书", "B站", "快手", "视频号", "TikTok", "YouTube", "微博", "知乎"]
const STAGES = ["冷启动（0-1w）", "成长期（1w-10w）", "扩张期（10w-50w）", "成熟期（50w+）", "矩阵/机构号"]
const FORMAT_KEYS = ["短视频", "图文笔记", "直播", "长视频", "口播", "图文长文"]

function parseDetail(detail: unknown): string {
  if (typeof detail === "string") return detail
  if (Array.isArray(detail)) return detail.map((d) => JSON.stringify(d)).join("；")
  try {
    return JSON.stringify(detail)
  } catch {
    return "未知错误"
  }
}

export default function ProfilePage() {
  const { toast } = useToast()
  const [form, setForm] = useState<ProfileForm>(EMPTY_FORM)
  const [name, setName] = useState("")
  const [building, setBuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState<string[]>([])
  const [pendingLoading, setPendingLoading] = useState(true)
  const [profiles, setProfiles] = useState<ProfileSummary[]>([])
  const [profilesLoading, setProfilesLoading] = useState(true)
  const [detail, setDetail] = useState<ProfileDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState<string | null>(null)

  const loadPending = async () => {
    setPendingLoading(true)
    try {
      const res = await fetch("/api/v1/content-library/accounts", { cache: "no-store" })
      if (res.ok) {
        const data = await res.json()
        const accts = data?.result?.accounts
        if (accts && typeof accts === "object") {
          setPending(Object.keys(accts).filter((k) => !k.startsWith("_")))
          return
        }
      }
      // 端点不可用时静默降级
      setPending([])
    } catch {
      setPending([])
    } finally {
      setPendingLoading(false)
    }
  }

  const loadProfiles = async () => {
    setProfilesLoading(true)
    try {
      const res = await fetch("/api/v1/content-library/profile", { cache: "no-store" })
      const data = await res.json().catch(() => ({}))
      const list = Array.isArray(data?.result?.profiles) ? data.result.profiles : []
      setProfiles(list)
    } catch {
      setProfiles([])
    } finally {
      setProfilesLoading(false)
    }
  }

  const openDetail = async (n: string) => {
    setDetailLoading(n)
    setDetail(null)
    try {
      const res = await fetch(`/api/v1/content-library/profile/${encodeURIComponent(n)}`, { cache: "no-store" })
      if (!res.ok) throw new Error(`接口返回 ${res.status}`)
      const data = await res.json().catch(() => ({}))
      setDetail(data?.result || null)
    } catch (e) {
      toast({ variant: "destructive", title: `读取「${n}」失败`, description: e instanceof Error ? e.message : String(e) })
    } finally {
      setDetailLoading(null)
    }
  }

  useEffect(() => {
    void loadPending()
    void loadProfiles()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const toggle = (listKey: "platforms" | "formats", v: string) => {
    setForm((prev) => {
      const cur = prev[listKey]
      return { ...prev, [listKey]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] }
    })
  }

  const setLink = (p: string, u: string) => {
    setForm((prev) => ({ ...prev, links: { ...prev.links, [p]: u } }))
  }

  const build = async () => {
    const n = name.trim()
    if (!n) {
      toast({ variant: "destructive", title: "请填写画像名称" })
      return
    }
    if (/[\\\/]/.test(n)) {
      toast({ variant: "destructive", title: `画像名不能包含 / 或 \\`, description: "请换掉后重试" })
      return
    }
    if (/[._\-]/.test(n.charAt(0))) {
      toast({ variant: "destructive", title: "画像名不能以 . _ - 开头", description: "请换掉后重试" })
      return
    }
    if (!form.platforms.length && !form.direction.trim()) {
      toast({ variant: "destructive", title: "请至少选择平台或填写内容方向" })
      return
    }
    setBuilding(true)
    setError(null)
    try {
      const res = await fetch("/api/v1/content-library/profile/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: n, form }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(parseDetail(data?.detail || data?.error || `接口返回 ${res.status}`))
      const createdName: string = data?.result?.name || n
      const filledDims: number | undefined = data?.result?.filled_dims
      toast({
        title: "基线画像已生成",
        description: `「${createdName}」已可用于创作引用${typeof filledDims === "number" ? `（${filledDims}/12 维）` : ""}`,
      })
      setName("")
      setForm(EMPTY_FORM)
      setDetail(null)
      await loadProfiles()
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(`画像构建失败：${msg}`)
      toast({ variant: "destructive", title: "画像构建失败", description: msg })
    } finally {
      setBuilding(false)
    }
  }

  const linkKeys = useMemo(() => {
    const set = new Set(form.platforms)
    PLATFORM_KEYS.forEach((p) => {
      if (form.links[p]) set.add(p)
    })
    return Array.from(set)
  }, [form.platforms, form.links])

  const filledCount = useMemo(() => {
    let n = 0
    if (form.accountStage) n++
    if (form.direction.trim()) n++
    if (form.reason.trim()) n++
    if (form.goal.trim()) n++
    if (form.platforms.length) n++
    if (form.formats.length) n++
    if (form.likes.trim()) n++
    if (form.tone.trim()) n++
    if (form.avoid.trim()) n++
    Object.values(form.links).forEach((v) => v && n++)
    return n
  }, [form])

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="PLATFORM · PROFILE"
        title="账号画像"
        description="沉淀人设六维基线：身份定位、内容风格、目标受众、平台资产、运营目标与内容红线。"
        actions={
          <Button variant="ghost" onClick={() => void loadPending()} disabled={pendingLoading}>
            {pendingLoading ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <RefreshCw className="h-4 w-4 mr-2" />}
            刷新
          </Button>
        }
      />

      <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
        {error && (
          <Card className="border-destructive/40 p-4">
            <div className="flex items-start gap-2 text-sm">
              <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
              <div>
                <p className="font-medium text-destructive">画像构建失败</p>
                <p className="mt-0.5 break-words text-xs text-foreground/70">{error}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  表单已就绪，端点 <code className="font-mono">POST /api/v1/content-library/profile/build</code> 恢复后可重新提交。
                </p>
              </div>
            </div>
          </Card>
        )}

        <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
          <Card className="p-4">
            <div className="space-y-4">
              <div>
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Fingerprint className="h-4 w-4 text-primary" /> 画像名称
                </div>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="如：美妆-素人号-小A" className="mt-1.5" />
                <p className="mt-1 text-xs text-muted-foreground">用于目录化存储，避免 / \ 等特殊字符。</p>
              </div>

              <div>
                <label className="text-xs font-medium text-foreground/80">运营平台</label>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {PLATFORMS.map((p) => (
                    <button
                      key={p}
                      type="button"
                      onClick={() => toggle("platforms", p)}
                      className={[
                        "rounded-full border px-2.5 py-1 text-xs transition",
                        form.platforms.includes(p) ? "border-primary bg-primary/15 text-foreground" : "border-border/80 text-muted-foreground hover:border-primary/50",
                      ].join(" ")}
                    >
                      {p}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-foreground/80">社媒主页链接</label>
                <div className="mt-1.5 space-y-2">
                  {linkKeys.length === 0 ? (
                    <p className="text-xs text-muted-foreground">先选择平台即可填写对应主页链接。</p>
                  ) : (
                    linkKeys.map((p) => (
                      <div key={p} className="flex items-center gap-2">
                        <Badge variant="outline" className="w-16 justify-center text-xs">{p}</Badge>
                        <Input value={form.links[p] || ""} onChange={(e) => setLink(p, e.target.value)} placeholder={`https://${p} 主页链接`} className="flex-1" />
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-foreground/80">起号状态</label>
                <select
                  value={form.accountStage}
                  onChange={(e) => setForm((prev) => ({ ...prev, accountStage: e.target.value }))}
                  className="mt-1.5 h-8 w-full rounded-md border border-input bg-background px-2 text-xs"
                >
                  <option value="">请选择</option>
                  {STAGES.map((s) => (
                    <option key={s} value={s}>{s}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-foreground/80">想做的方向</label>
                <Textarea value={form.direction} onChange={(e) => setForm((prev) => ({ ...prev, direction: e.target.value }))} rows={2} placeholder="例如：母婴好物测评 + 育儿知识科普" className="mt-1.5" />
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="text-xs font-medium text-foreground/80">为什么做 / 我的优势</label>
                  <Textarea value={form.reason} onChange={(e) => setForm((prev) => ({ ...prev, reason: e.target.value }))} rows={2} className="mt-1.5" />
                </div>
                <div>
                  <label className="text-xs font-medium text-foreground/80">运营目标</label>
                  <Textarea value={form.goal} onChange={(e) => setForm((prev) => ({ ...prev, goal: e.target.value }))} rows={2} placeholder="如：3 个月做到 5w 粉，跑通带货闭环" className="mt-1.5" />
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-foreground/80">想产出的内容形式</label>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {FORMAT_KEYS.map((f) => (
                    <button
                      key={f}
                      type="button"
                      onClick={() => toggle("formats", f)}
                      className={[
                        "rounded-full border px-2.5 py-1 text-xs transition",
                        form.formats.includes(f) ? "border-primary bg-primary/15 text-foreground" : "border-border/80 text-muted-foreground hover:border-primary/50",
                      ].join(" ")}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs font-medium text-foreground/80">喜欢看的内容 / 对标账号</label>
                <Textarea value={form.likes} onChange={(e) => setForm((prev) => ({ ...prev, likes: e.target.value }))} rows={2} className="mt-1.5" />
              </div>

              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="text-xs font-medium text-foreground/80">期望调性</label>
                  <Input value={form.tone} onChange={(e) => setForm((prev) => ({ ...prev, tone: e.target.value }))} placeholder="如：亲切、专业、有梗" className="mt-1.5" />
                </div>
                <div>
                  <label className="text-xs font-medium text-foreground/80">不做的内容 / 红线</label>
                  <Input value={form.avoid} onChange={(e) => setForm((prev) => ({ ...prev, avoid: e.target.value }))} placeholder="如：不做医疗承诺、不做擦边" className="mt-1.5" />
                </div>
              </div>

              <div className="flex items-center gap-2 border-t border-border/60 pt-3">
                <Button onClick={build} disabled={building}>
                  {building ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                  生成基线画像
                </Button>
                <Button variant="outline" onClick={() => { setName(""); setForm(EMPTY_FORM); setError(null) }}>
                  重置
                </Button>
              </div>
            </div>
          </Card>

          <div className="space-y-4">
            <Card className="p-4">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium">基线完整度</span>
                <Badge variant="accent" className="text-xs">{filledCount}/12 项</Badge>
              </div>
              <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${Math.min(100, (filledCount / 12) * 100)}%` }} />
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {filledCount === 0 ? "还没有填写任何维度。" : filledCount < 6 ? "先补齐方向、目标与平台，画像才可用。" : "基线已可用，链接派生维度待 AI 分析。"}
              </p>
            </Card>

            <Card className="p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <Target className="h-4 w-4 text-primary" /> 六维基线
              </div>
              <ul className="space-y-2">
                {[
                  { label: "身份定位", val: form.direction || "（未填）", done: !!form.direction.trim() },
                  { label: "内容风格", val: form.tone || "（待 AI 分析）", done: !!form.tone.trim() },
                  { label: "运营目标", val: form.goal || "（未填）", done: !!form.goal.trim() },
                  { label: "内容形式", val: form.formats.join("、") || "（未选）", done: form.formats.length > 0 },
                  { label: "运营平台", val: form.platforms.join("、") || "（未选）", done: form.platforms.length > 0 },
                  { label: "内容红线", val: form.avoid || "（未填）", done: !!form.avoid.trim() },
                ].map((row) => (
                  <li key={row.label} className="rounded-lg border p-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium">{row.label}</span>
                      {row.done ? <ClipboardCheck className="h-3.5 w-3.5 text-primary" /> : <span className="text-xs text-muted-foreground">待补</span>}
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{row.val}</p>
                  </li>
                ))}
              </ul>
            </Card>

            <Card className="p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <NotebookPen className="h-4 w-4 text-primary" /> 已登录账号（可作画像资产）
              </div>
              {pendingLoading ? (
                <div className="py-6 text-center text-xs text-muted-foreground">
                  <Loader2 className="mx-auto mb-1 h-4 w-4 animate-spin" /> 正在查询…
                </div>
              ) : pending.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">暂未发现已登录平台账号。</p>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {pending.map((p) => (
                    <Badge key={p} variant="secondary" className="text-xs">{p}</Badge>
                  ))}
                </div>
              )}
              <p className="mt-2 text-xs text-muted-foreground">数据源：GET /api/v1/content-library/accounts</p>
            </Card>

            <Card className="p-4">
              <div className="mb-2 flex items-center justify-between text-sm font-medium">
                <span className="flex items-center gap-2">
                  <Fingerprint className="h-4 w-4 text-primary" /> 画像库
                </span>
                <span className="flex items-center gap-2">
                  {profilesLoading ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />
                  ) : (
                    <Badge variant="outline" className="text-xs">共 {profiles.length}</Badge>
                  )}
                  <Button variant="ghost" size="sm" onClick={() => void loadProfiles()} disabled={profilesLoading}>
                    <RefreshCw className="h-3.5 w-3.5" />
                  </Button>
                </span>
              </div>
              {profilesLoading ? (
                <p className="py-4 text-center text-xs text-muted-foreground">正在加载…</p>
              ) : profiles.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">
                  还没有画像。填写左侧表单后点「生成基线画像」即可持久化。
                </p>
              ) : (
                <div className="space-y-1.5">
                  {profiles.map((p) => {
                    const filling = detailLoading === p.name
                    return (
                      <button
                        key={p.name}
                        type="button"
                        onClick={() => void openDetail(p.name)}
                        className="flex w-full items-center gap-2 rounded-lg border p-2.5 text-left transition hover:border-primary/40"
                      >
                        <Fingerprint className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className="min-w-0 flex-1 truncate text-sm">{p.name}</span>
                        {p.updated_at ? (
                          <span className="font-mono text-[10px] text-muted-foreground">{p.updated_at.slice(0, 10)}</span>
                        ) : null}
                        {p.total_dims ? (
                          <Badge variant="outline" className="text-xs">{p.filled_dims ?? 0}/{p.total_dims}</Badge>
                        ) : null}
                        {filling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                      </button>
                    )
                  })}
                </div>
              )}
              <p className="mt-2 text-xs text-muted-foreground">
                数据源：GET /api/v1/content-library/profile · 存于后端 profiles 目录
              </p>
            </Card>

            {detail && (
              <Card className="p-4">
                <div className="mb-3 flex items-start justify-between">
                  <div className="min-w-0">
                    <p className="text-sm font-medium">{detail.name}</p>
                    {detail.updated_at && (
                      <p className="font-mono text-[10px] text-muted-foreground">更新 {detail.updated_at}</p>
                    )}
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => setDetail(null)}>关闭</Button>
                </div>
                {typeof detail.filled_dims === "number" && detail.total_dims ? (
                  <div className="mb-3">
                    <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                      <span>完整度</span>
                      <span>{detail.filled_dims}/{detail.total_dims}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full bg-primary"
                        style={{ width: `${Math.min(100, (detail.filled_dims / detail.total_dims) * 100)}%` }}
                      />
                    </div>
                  </div>
                ) : null}
                <div className="space-y-2">
                  {Object.entries(detail.baseline || {}).map(([k, v]) => (
                    <div key={k} className="rounded-lg border p-2.5">
                      <div className="text-xs font-medium">{k}</div>
                      <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">{v || "—"}</p>
                    </div>
                  ))}
                </div>
                <p className="mt-3 text-xs text-muted-foreground">
                  引擎：{detail.engine || "native-baseline"}（仅基线，无后台 AI 增强）
                </p>
              </Card>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5" />
          画像与 /persona（Persona Studio）是不同模块：此处为人设内容画像，非进程托管。
          <ExternalLink className="h-3 w-3" />
        </div>
      </div>
    </div>
  )
}
