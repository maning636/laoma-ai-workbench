"use client"

/**
 * 注册码（License）设置卡片。
 *
 * 位置：`/settings` → "更多设置" → 紧跟在 `CloudSubscriptionCard` 之后。
 *
 * 双轨授权模型（D1=C）：
 *   - 注册码 = 本地授权条目（离线可用，Ed25519 验签在后端）
 *   - 订阅   = 云端配额
 *   - 最终生效 = 注册码 ∩ 订阅（后端 `/effective-flags` 已完成交集）
 *
 * 只读模式（D4）：
 *   - 注册码过期 + 宽限期满 → `readOnly=true` → 顶部红色横幅提示
 *   - 写操作由后端 403 拦截，前端不额外做拦截（避免误判），但视觉上给出强提示
 *
 * 交互：
 *   - `useQuery` 拉 `/api/v1/license/status` 和 `/api/v1/license/effective-flags`
 *   - `useMutation` 触发 `/activate` 和 `DELETE /`
 *   - 激活失败（HTTP 400）时把后端 `detail` 的中文错误**原样**toast 展示
 */

import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Coins,
  Info,
  KeyRound,
  Loader2,
  Lock,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UploadCloud,
  XCircle,
} from "lucide-react"

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
import { Label } from "@/components/ui/label"
import { Separator } from "@/components/ui/separator"
import { useToast } from "@/components/ui/use-toast"
import { cloudAuth } from "@/lib/cloud-auth"
import {
  ENTITLEMENTS,
  ENTITLEMENT_LABELS,
  licenseStatusLabel,
  licenseStatusTone,
  type LicenseEffectiveFlagsResponse,
  type LicenseStatusResponse,
  type LicenseStatusTone,
} from "@/lib/license"

// 后端 API 路径（走 next.config.ts 的 rewrite → 后端 /api/v1/license）
const LICENSE_BASE = "/api/v1/license"

/** 徽标在 5 种色调下的语义化 class（深浅主题都可用） */
const TONE_BADGE_CLASS: Record<LicenseStatusTone, string> = {
  muted: "border-border/70 bg-muted/40 text-foreground/70 hover:bg-muted/60",
  success:
    "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 shadow-glow-purple",
  warning:
    "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400 hover:bg-amber-500/20",
  danger:
    "border-destructive/40 bg-destructive/10 text-destructive hover:bg-destructive/20",
  info: "border-sky-500/40 bg-sky-500/10 text-sky-600 dark:text-sky-400 hover:bg-sky-500/20",
}

/** 状态左侧圆点的语义化 class */
const TONE_DOT_CLASS: Record<LicenseStatusTone, string> = {
  muted: "bg-muted-foreground/50",
  success: "bg-primary",
  warning: "bg-amber-500",
  danger: "bg-destructive",
  info: "bg-sky-500",
}

/** 只读 / 状态提示条的语义化 class */
const TONE_BANNER_CLASS: Record<LicenseStatusTone, string> = {
  muted: "border-border/70 bg-muted/40 text-foreground/80",
  success: "border-primary/30 bg-primary/10 text-foreground",
  warning:
    "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300",
  danger: "border-destructive/40 bg-destructive/10 text-destructive",
  info: "border-sky-500/30 bg-sky-500/10 text-sky-700 dark:text-sky-300",
}

/** 日期格式化：失败时原样返回，不抛错 */
function formatDate(input: string | null | undefined): string {
  if (!input) return "-"
  const d = new Date(input)
  if (Number.isNaN(d.getTime())) return input
  return d.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

/** 提取错误文案：Error → message，其他 → String() */
function parseDetail(err: unknown): string {
  if (err instanceof Error && err.message) return err.message
  return String(err)
}

export function LicenseCard() {
  const { toast } = useToast()
  const queryClient = useQueryClient()
  const [code, setCode] = useState("")

  // 当前注册码状态（纯本地，不联网）
  const {
    data: status,
    isLoading: isLoadingStatus,
    isError: isStatusError,
    error: statusError,
    refetch: refetchStatus,
  } = useQuery({
    queryKey: ["license", "status"],
    queryFn: async () => {
      const res = await fetch(`${LICENSE_BASE}/status`, { cache: "no-store" })
      if (!res.ok) throw new Error(`加载失败 (HTTP ${res.status})`)
      return (await res.json()) as LicenseStatusResponse
    },
    retry: false,
  })

  // 生效后的 flag（后端已完成交集运算）
  const { data: effectiveFlags } = useQuery({
    queryKey: ["license", "effective-flags"],
    queryFn: async () => {
      const res = await fetch(`${LICENSE_BASE}/effective-flags`, { cache: "no-store" })
      if (!res.ok) throw new Error(`加载失败 (HTTP ${res.status})`)
      return (await res.json()) as LicenseEffectiveFlagsResponse
    },
    retry: false,
  })

  // 激活注册码
  const activate = useMutation({
    mutationFn: async (payload: { code: string }) => {
      const res = await fetch(`${LICENSE_BASE}/activate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      // 400 时后端返回 { detail: "中文错误" }，原样展示给用户
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new Error(body?.detail || `激活失败 (HTTP ${res.status})`)
      }
      return (await res.json()) as LicenseStatusResponse
    },
    onSuccess: () => {
      setCode("")
      void queryClient.invalidateQueries({ queryKey: ["license"] })
      toast({
        title: "注册码已激活",
        description: "本地授权条目已更新，功能已重新计算。",
      })
    },
    onError: (err) => {
      toast({
        variant: "destructive",
        title: "激活失败",
        description: parseDetail(err),
      })
    },
  })

  // 同步到云端（线下人工充值模式）
  // 注册码原文不出本机：后端从本地 license.json 读取后转发给云端。
  // 这里只带云端登录态，让云端知道给哪个账户开通。
  const syncCloud = useMutation({
    mutationFn: async () => {
      const accessToken = await cloudAuth.getAccessToken()
      const res = await fetch(`${LICENSE_BASE}/sync-cloud`, {
        method: "POST",
        headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      })
      if (!res.ok) {
        const body = await res.json().catch(() => null)
        throw new Error(body?.detail || `同步失败 (HTTP ${res.status})`)
      }
      return (await res.json()) as {
        ok: boolean
        result?: { creditsAdded?: number; creditsSkipped?: boolean }
      }
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ["license"] })
      const added = Number(data?.result?.creditsAdded ?? 0)
      toast({
        title: "已同步到云端",
        description:
          added > 0
            ? `云端订阅已开通，本次到账积分 ${added}。`
            : "云端订阅已开通或已更新（积分无新增）。",
      })
    },
    onError: (err) => {
      toast({
        variant: "destructive",
        title: "同步到云端失败",
        description: parseDetail(err),
      })
    },
  })

  // 清除注册码
  const clear = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${LICENSE_BASE}/`, { method: "DELETE" })
      if (!res.ok) throw new Error(`清除失败 (HTTP ${res.status})`)
      return (await res.json()) as LicenseStatusResponse
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["license"] })
      toast({ title: "注册码已清除", description: "已回到 Community 默认配置。" })
    },
    onError: (err) => {
      toast({
        variant: "destructive",
        title: "清除失败",
        description: parseDetail(err),
      })
    },
  })

  const license = status?.license
  const readOnly = status?.readOnly ?? effectiveFlags?.readOnly ?? false
  const tone = license ? licenseStatusTone(license.status) : "muted"
  const hasToken = license?.hasToken ?? false

  // 只读模式下的提示文案（D4）
  const readOnlyBanner = readOnly
    ? license?.status === "expired"
      ? {
          title: "注册码已过期，当前处于只读模式",
          desc: "能看不能新增：新建、发布、写入类操作已被后端拒绝。续费或更换注册码后可恢复写入。",
          tone: "danger" as const,
          Icon: Lock,
        }
      : {
          title: "当前只读",
          desc: license?.message || "后端标记为只读，请检查注册码状态。",
          tone: "warning" as const,
          Icon: AlertTriangle,
        }
    : null

  return (
    <Card className="border-border/70 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-foreground">
          <KeyRound className="h-5 w-5 text-foreground/70" />
          注册码
        </CardTitle>
        <CardDescription className="text-muted-foreground">
          本地授权条目（离线可用）。最终生效功能 = 注册码授权 ∩ 云端订阅配额。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 只读 / 状态横幅 */}
        {readOnlyBanner ? (
          <div
            className={`flex items-start gap-2 rounded-lg border p-3 text-xs ${TONE_BANNER_CLASS[readOnlyBanner.tone]}`}
            role="alert"
          >
            <readOnlyBanner.Icon className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="min-w-0 space-y-1">
              <div className="font-medium">{readOnlyBanner.title}</div>
              <div className="text-foreground/70">{readOnlyBanner.desc}</div>
            </div>
          </div>
        ) : null}

        {/* 状态栏 */}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-4">
          {/* 授权状态 */}
          <div className="rounded-xl border border-border/70 bg-card p-4">
            <div className="text-xs text-muted-foreground">授权状态</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <span
                aria-hidden
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${TONE_DOT_CLASS[tone]}`}
              />
              <Badge
                variant="outline"
                className={`text-xs ${TONE_BADGE_CLASS[tone]}`}
              >
                {license ? licenseStatusLabel(license.status) : "加载中"}
              </Badge>
              {license?.customer ? (
                <span className="text-xs text-muted-foreground">
                  · {license.customer}
                </span>
              ) : null}
            </div>
            {license?.licenseId ? (
              <code className="mt-2 block truncate text-[11px] text-muted-foreground">
                {license.licenseId}
              </code>
            ) : null}
          </div>

          {/* 到期时间 */}
          <div className="rounded-xl border border-border/70 bg-card p-4">
            <div className="text-xs text-muted-foreground">到期时间</div>
            <div className="mt-2 flex items-center gap-1.5 text-lg font-semibold text-foreground">
              <Clock className="h-4 w-4 text-foreground/60" />
              <span className="break-all">
                {license ? formatDate(license.expiresAt) : "-"}
              </span>
            </div>
            {license?.status === "grace" ? (
              <div className="mt-1 text-xs text-amber-600 dark:text-amber-400">
                宽限期内 · 剩 {license.graceDays} 天
              </div>
            ) : null}
            {license?.status === "not_yet_valid" ? (
              <div className="mt-1 text-xs text-sky-600 dark:text-sky-400">
                尚未生效（检查系统时间）
              </div>
            ) : null}
          </div>

          {/* 云端订阅 */}
          <div className="rounded-xl border border-border/70 bg-card p-4">
            <div className="text-xs text-muted-foreground">云端订阅</div>
            <div className="mt-2 flex items-center gap-1.5 text-lg font-semibold text-foreground">
              {effectiveFlags?.cloudAvailable ? (
                <CheckCircle2 className="h-4 w-4 text-primary" />
              ) : (
                <Info className="h-4 w-4 text-foreground/60" />
              )}
              <span>{effectiveFlags?.cloudAvailable ? "已连接" : "未连接"}</span>
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {effectiveFlags?.cloudAvailable
                ? "已同步云端配额"
                : "离线模式：按 Community 兜底"}
            </div>
          </div>
          {/* 积分额度 */}
          <div className="rounded-xl border border-border/70 bg-card p-4">
            <div className="text-xs text-muted-foreground">积分额度</div>
            <div className="mt-2 flex items-center gap-1.5 text-lg font-semibold text-foreground">
              <Coins className="h-4 w-4 text-foreground/60" />
              <span>{license?.credits ? license.credits : "-"}</span>
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              {license?.credits
                ? "随注册码下发，同步到云端后到账"
                : "该注册码不含积分额度"}
            </div>
          </div>
        </div>

        {/* 已授权条目 */}
        <div className="space-y-2">
          <div className="text-xs text-muted-foreground">已授权条目</div>
          <div className="flex flex-wrap gap-1.5">
            {ENTITLEMENTS.map((key) => {
              const granted = license?.entitlements?.includes(key) ?? false
              const label = ENTITLEMENT_LABELS[key]
              return (
                <Badge
                  key={key}
                  variant="outline"
                  className={
                    granted
                      ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
                      : "border-border/60 bg-muted/30 text-foreground/45"
                  }
                  title={`${label}：${granted ? "已授权" : "未授权"}`}
                >
                  {label}
                </Badge>
              )
            })}
          </div>
        </div>

        {/* 后端消息（激活成功 / 无效等） */}
        {license && license.message && license.status !== "missing" ? (
          <div className="rounded-lg border border-border/70 bg-muted/30 p-2.5 text-xs text-muted-foreground">
            {license.message}
          </div>
        ) : null}

        <Separator className="bg-border/60" />

        {/* 激活输入 */}
        <div className="space-y-2">
          <Label
            htmlFor="license-code"
            className="text-xs text-muted-foreground"
          >
            输入 / 更换注册码
          </Label>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              id="license-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="PRISM1.…"
              className="min-w-0 flex-1 font-mono text-xs"
              disabled={activate.isPending}
              onKeyDown={(e) => {
                if (e.key === "Enter" && code.trim()) {
                  activate.mutate({ code: code.trim() })
                }
              }}
            />
            <Button
              size="sm"
              onClick={() => activate.mutate({ code: code.trim() })}
              disabled={!code.trim() || activate.isPending}
              className="h-9"
            >
              {activate.isPending ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : (
                <ShieldCheck className="mr-1.5 h-4 w-4" />
              )}
              激活
            </Button>
          </div>
        </div>

        {/* 操作按钮 */}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            className="border-border/70 bg-card text-foreground hover:bg-accent/40"
            onClick={() => {
              void refetchStatus()
              void queryClient.invalidateQueries({ queryKey: ["license"] })
            }}
            disabled={isLoadingStatus}
          >
            {isLoadingStatus ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="mr-1.5 h-4 w-4" />
            )}
            刷新状态
          </Button>

          <Button
            size="sm"
            variant="secondary"
            className="border-border/70 bg-card text-foreground hover:bg-accent/40"
            onClick={() => syncCloud.mutate()}
            disabled={syncCloud.isPending || !hasToken}
            title={
              hasToken
                ? "把本地注册码同步到云端(开通云端能力,积分额度一并到账)"
                : "当前没有已保存的注册码"
            }
          >
            {syncCloud.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <UploadCloud className="mr-1.5 h-4 w-4" />
            )}
            同步到云端
          </Button>

          <Button
            size="sm"
            variant="secondary"
            className="border-border/70 bg-card text-foreground hover:bg-accent/40"
            onClick={() => clear.mutate()}
            disabled={clear.isPending || !hasToken}
            title={hasToken ? "清除本地注册码" : "当前没有已保存的注册码"}
          >
            {clear.isPending ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="mr-1.5 h-4 w-4" />
            )}
            清除注册码
          </Button>
        </div>

        {/* 状态读取失败 */}
        {isStatusError ? (
          <div className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-2.5 text-xs text-destructive">
            <XCircle className="h-4 w-4 shrink-0" />
            <span>状态读取失败：{parseDetail(statusError)}</span>
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

export default LicenseCard
