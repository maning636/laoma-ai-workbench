"use client"

import { useEffect, useState } from "react"
import Link from "next/link"
import {
  BadgeCheck,
  KeyRound,
  Loader2,
  LogOut,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UserRound,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog"
import { Progress } from "@/components/ui/progress"
import { useToast } from "@/components/ui/use-toast"
import {
  cloudAuth,
  type CloudUser,
  type SubscriptionStatus,
} from "@/lib/cloud-auth"
import { backendBaseUrl } from "@/lib/env"
import {
  describeCloudLlmAvailability,
  probeCloudLlmAvailability,
  type CloudLlmAvailability,
} from "@/lib/cloud-llm-availability"
import { useLicenseHeartbeat } from "@/hooks/useLicenseHeartbeat"

const REASON_LABELS: Record<string, string> = {
  active: "订阅生效中",
  free: "免费额度",
  expired: "订阅已过期",
  cancelled: "订阅已取消",
  unauthenticated: "未登录",
  offline: "云端不可达",
  cloud_unreachable: "云端不可达",
}

function formatRemaining(remaining: number): string {
  if (remaining === -1 || remaining < 0) return "无限"
  return String(remaining)
}

/**
 * 订阅 / 账户卡:展示登录态、订阅计划与剩余额度,并支持:
 *   - 登出
 *   - 手动刷新订阅(心跳)
 *   - 订阅用户清理本地自配 key(强制切换到订阅模式)
 *
 * 放置位置:settings 页 "更多设置" 顶部;不影响现有区块结构。
 */
export function CloudSubscriptionCard() {
  const { toast } = useToast()
  const { status, lastCheckedAt, error, refreshing, refresh } = useLicenseHeartbeat()
  const [user, setUser] = useState<CloudUser | null>(null)
  const [loadingUser, setLoadingUser] = useState(true)
  const [clearingKeys, setClearingKeys] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)
  const [logoutOpen, setLogoutOpen] = useState(false)
  // P7:云端 LLM 是否已配置。只有明确"未配置"才调整文案;
  // 探测失败(unknown)保持原样,不让一次网络抖动改变用户看到的信息。
  const [cloudAvailability, setCloudAvailability] =
    useState<CloudLlmAvailability>("unknown")
  const [cloudAvailabilityMessage, setCloudAvailabilityMessage] = useState("")

  useEffect(() => {
    let cancelled = false
    void (async () => {
      const r = await probeCloudLlmAvailability()
      if (cancelled) return
      setCloudAvailability(r.availability)
      setCloudAvailabilityMessage(
        describeCloudLlmAvailability(r.availability, r.message),
      )
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    let mounted = true
    ;(async () => {
      try {
        const u = await cloudAuth.me()
        if (mounted) setUser(u)
      } catch {
        if (mounted) setUser(null)
      } finally {
        if (mounted) setLoadingUser(false)
      }
    })()
    return () => {
      mounted = false
    }
  }, [])

  const handleRefresh = async () => {
    await refresh()
  }

  const handleLogout = async () => {
    try {
      await cloudAuth.logout()
      setUser(null)
      toast({ title: "已退出登录", description: "云端账号凭证已清除。" })
      // 心跳会自然降级为 unauthenticated
      void refresh()
    } catch (err) {
      toast({
        variant: "destructive",
        title: "退出失败",
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  const handleClearLocalKeys = async () => {
    setClearingKeys(true)
    try {
      const results: { source: string; ok: boolean; error?: string }[] = []

      // 1) 后端 SQLite `ai_model_configs` 里的 API key(通过 DELETE 端点)
      try {
        const listResp = await fetch(`${backendBaseUrl}/api/v1/ai/model-configs`, {
          cache: "no-store",
        })
        if (listResp.ok) {
          const listData: any = await listResp.json().catch(() => ({}))
          const items: any[] = Array.isArray(listData)
            ? listData
            : Array.isArray(listData?.data)
              ? listData.data
              : []
          // 后端删除端点以 `service_type` 作为主键路径参数
          for (const item of items) {
            const serviceType = item?.service_type
            if (!serviceType) continue
            try {
              const delResp = await fetch(
                `${backendBaseUrl}/api/v1/ai/model-configs/${encodeURIComponent(serviceType)}`,
                { method: "DELETE" },
              )
              results.push({
                source: `ai_model_configs:${serviceType}`,
                ok: delResp.ok,
                error: delResp.ok ? undefined : `HTTP ${delResp.status}`,
              })
            } catch (err) {
              results.push({
                source: `ai_model_configs:${serviceType}`,
                ok: false,
                error: err instanceof Error ? err.message : "network",
              })
            }
          }
        }
      } catch {
        results.push({ source: "ai_model_configs", ok: false, error: "fetch_failed" })
      }

      // 2) 提示需要手动删除 hermes-config(设计文档 §2.3)
      const deleted = results.filter((r) => r.ok).length
      const total = results.length
      toast({
        title: "已清理本地 AI 密钥",
        description:
          total === 0
            ? "未在 ai_model_configs 中发现 API key 记录"
            : `ai_model_configs:${deleted}/${total} 已清除。若使用 Hermes 自配 key,请手动删除 hermes-home/config.yaml 中的 key 段。`,
      })
    } catch (err) {
      toast({
        variant: "destructive",
        title: "清理失败",
        description: err instanceof Error ? err.message : String(err),
      })
    } finally {
      setClearingKeys(false)
      setConfirmClear(false)
    }
  }

  const statusLabel = status ? (REASON_LABELS[status.reason] || status.reason || "未知") : "加载中"
  const showCredCard = Boolean(status)
  const showActionButtons = Boolean(user)

  return (
    <Card className="border-border/70 bg-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-foreground">
          <ShieldCheck className="h-5 w-5 text-foreground/70" />
          订阅与云端账号
        </CardTitle>
        <CardDescription className="text-muted-foreground">
          {cloudAvailability === "unavailable"
            ? "云端订阅与账号仍然可用;云端 AI 未配置,AI 对话当前走本地模型。"
            : "登录后使用云端 AI 与高级 Prompt;未登录时以离线模式运行。"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="space-y-4">
          {cloudAvailability === "unavailable" ? (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs leading-5 text-amber-600">
              {cloudAvailabilityMessage}
            </div>
          ) : null}
          {/* 状态行 */}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div className="rounded-xl border border-border/70 bg-card p-4">
              <div className="text-xs text-muted-foreground">登录状态</div>
              <div className="mt-2 flex items-center gap-2 text-lg font-semibold text-foreground">
                {loadingUser ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : user ? (
                  <>
                    <UserRound className="h-4 w-4" />
                    {user.username}
                  </>
                ) : (
                  "未登录"
                )}
              </div>
              {user?.email ? (
                <div className="mt-1 text-xs text-foreground/50">{user.email}</div>
              ) : null}
            </div>

            <div className="rounded-xl border border-border/70 bg-card p-4">
              <div className="text-xs text-muted-foreground">订阅计划</div>
              <div className="mt-2 text-lg font-semibold text-foreground">
                {status?.is_pro ? "Pro" : "Free"}
              </div>
              <div className="mt-1 text-xs text-foreground/50">
                {status?.expire_at ? `到期 ${new Date(status.expire_at).toLocaleString()}` : "未设置到期"}
              </div>
            </div>

            <div className="rounded-xl border border-border/70 bg-card p-4">
              <div className="text-xs text-muted-foreground">剩余额度</div>
              <div className="mt-2 text-lg font-semibold text-foreground">
                {showCredCard ? formatRemaining(status!.remaining) : "-"}
              </div>
              <div className="mt-1 text-xs text-foreground/50">
                已用 {status?.used ?? 0}/{status?.quota ?? 0}
              </div>
            </div>
          </div>

          {/* 状态徽章 + 进度 */}
          {showCredCard && status ? (
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2 text-xs text-foreground/70">
                <BadgeCheck className="h-4 w-4" />
                <span>{statusLabel}</span>
                {lastCheckedAt ? (
                  <span className="text-foreground/45">
                    · 最近校验 {new Date(lastCheckedAt).toLocaleTimeString()}
                  </span>
                ) : null}
              </div>
              {status.quota !== -1 && status.quota > 0 ? (
                <Progress
                  value={Math.min(100, Math.round((status.used / Math.max(1, status.quota)) * 100))}
                  className="h-2"
                />
              ) : null}
            </div>
          ) : null}

          {error ? (
            <div className="rounded-lg border border-red-400/30 bg-red-500/10 p-3 text-xs text-red-300">
              心跳校验失败:{error}
            </div>
          ) : null}

          {/* 操作 */}
          <div className="flex flex-wrap items-center gap-2">
            <Link href={`/login?redirect=/settings`}>
              <Button
                variant="secondary"
                className="border-border/70 bg-card text-foreground hover:bg-accent/40"
                disabled={Boolean(user)}
              >
                <UserRound className="mr-2 h-4 w-4" />
                {user ? "已登录" : "登录 / 注册"}
              </Button>
            </Link>

            <Button
              onClick={handleRefresh}
              variant="secondary"
              className="border-border/70 bg-card text-foreground hover:bg-accent/40"
              disabled={refreshing || !user}
            >
              {refreshing ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="mr-2 h-4 w-4" />
              )}
              刷新订阅
            </Button>

            {status?.valid ? (
              <Button
                onClick={() => setConfirmClear(true)}
                variant="secondary"
                className="border-border/70 bg-card text-foreground hover:bg-accent/40"
                disabled={clearingKeys}
              >
                {clearingKeys ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="mr-2 h-4 w-4" />
                )}
                清除本地 key
              </Button>
            ) : null}

            {showActionButtons ? (
              <AlertDialog open={logoutOpen} onOpenChange={setLogoutOpen}>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="secondary"
                    className="ml-auto border-border/70 bg-card text-foreground hover:bg-accent/40"
                  >
                    <LogOut className="mr-2 h-4 w-4" />
                    退出登录
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>退出登录?</AlertDialogTitle>
                    <AlertDialogDescription>
                      将清除本地 JWT,不再走云端 AI。若仍需要云端功能,重新登录后恢复。
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>取消</AlertDialogCancel>
                    <AlertDialogAction onClick={handleLogout}>退出</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            ) : null}
          </div>

          {status?.valid ? (
            <div className="rounded-xl border border-dashed border-border/70 bg-card/20 px-4 py-3 text-xs leading-5 text-muted-foreground">
              <span className="inline-flex items-center gap-1 text-foreground/75">
                <KeyRound className="h-3.5 w-3.5" />
                订阅已生效
              </span>
              ,本地自配 key 与云端 AI 冗余。你可以点击上方「清除本地 key」按钮删除
              <code className="mx-1 rounded bg-popover px-1">ai_model_configs</code>
              中的 API key;Hermes 自配 key 需手动在 hermes-home 配置目录中清理。
            </div>
          ) : null}
        </div>

        <AlertDialog open={confirmClear} onOpenChange={setConfirmClear}>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>确认清除本地 API key?</AlertDialogTitle>
              <AlertDialogDescription>
                将从 <code className="rounded bg-popover px-1">ai_model_configs</code> 表删除
                已保存的模型 key 记录。订阅模式仍使用云端 AI,不影响使用;若需回退到离线模式,请重新配置 key。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction
                onClick={async () => {
                  await handleClearLocalKeys()
                }}
              >
                清除
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </CardContent>
    </Card>
  )
}
