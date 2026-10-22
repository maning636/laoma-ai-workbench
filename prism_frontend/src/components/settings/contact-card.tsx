"use client"

/**
 * 「联系我们」设置卡片（线下人工充值模式的用户联系入口）。
 *
 * 位置：`/settings` → "更多设置" → 紧跟在 `LicenseCard` 之后。
 *
 * 线上支付下线后，这个卡片承担两件事：
 *   1. **人工充值入口** —— 用户要加购积分 / 开通功能，唯一的路径是加产品方微信；
 *   2. **用户沉淀** —— 微信是答疑、新版本通知、复购的主阵地。
 *
 * 流程与官网（https://maning789link.top）一致：
 *   扫个人微信码 → 备注来意 → 产品方把用户拉进对应微信群。
 * 素材说明：
 *   - 微信号来自 `NEXT_PUBLIC_CONTACT_WECHAT_ID`（构建时注入）；
 *   - 二维码来自 `NEXT_PUBLIC_CONTACT_QR`（默认 `/wechat-contact-qr.png`）。
 *   - 二维码图片由运营提供并放进 `prism_frontend/public/`；未提供时显示占位提示，
 *     **不会**露出一个失效的图。
 */

import { useState } from "react"
import { Check, Copy, MessageCircle, QrCode, TriangleAlert, Users } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { useToast } from "@/components/ui/use-toast"
import {
  CONTACT_GROUP_URL,
  CONTACT_NOTICE,
  CONTACT_QR,
  CONTACT_WECHAT_ID,
  RECHARGE_GUIDE,
  hasContactQr,
  hasContactWechat,
} from "@/lib/contact"

export function ContactCard() {
  const { toast } = useToast()
  const [copied, setCopied] = useState(false)
  // 二维码图片加载失败（文件缺失 / 路径配错）→ 降级为文字提示，绝不留破图
  const [qrBroken, setQrBroken] = useState(false)

  const wechatId = CONTACT_WECHAT_ID.trim()
  const groupUrl = CONTACT_GROUP_URL.trim()
  const qr = CONTACT_QR.trim()
  const showQr = hasContactQr()
  const showWechat = hasContactWechat()

  const copyWechat = async () => {
    if (!wechatId) return
    try {
      await navigator.clipboard.writeText(wechatId)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
      toast({ title: "微信号已复制", description: wechatId })
    } catch {
      toast({
        variant: "destructive",
        title: "复制失败",
        description: "请手动选中并复制微信号。",
      })
    }
  }

  return (
    <Card className="border-border/70 bg-card" id="contact">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-foreground">
          <MessageCircle className="h-5 w-5 text-foreground/70" />
          联系我们
        </CardTitle>
        <CardDescription className="text-muted-foreground">
          {RECHARGE_GUIDE}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 个人微信 */}
        {showWechat ? (
          <div className="rounded-xl border border-border/70 bg-card p-4">
            <div className="text-xs text-muted-foreground">产品方微信</div>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <code className="select-all break-all font-mono text-sm text-foreground">
                {wechatId}
              </code>
              <Button
                size="sm"
                variant="secondary"
                className="h-8 border-border/70 bg-card text-foreground hover:bg-accent/40"
                onClick={() => void copyWechat()}
              >
                {copied ? (
                  <Check className="mr-1.5 h-3.5 w-3.5 text-primary" />
                ) : (
                  <Copy className="mr-1.5 h-3.5 w-3.5" />
                )}
                {copied ? "已复制" : "复制"}
              </Button>
            </div>
            <div className="mt-1.5 text-xs text-muted-foreground">
              添加时备注「老马AI工作台 + 你的账号」,方便核对订单。
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-border/70 bg-muted/30 p-4 text-xs text-muted-foreground">
            微信号尚未配置（构建时未设置
            <code className="mx-1 font-mono">NEXT_PUBLIC_CONTACT_WECHAT_ID</code>
            ）。
          </div>
        )}

        {/* 微信二维码 */}
        {showQr ? (
          <div className="space-y-3 rounded-xl border border-border/70 bg-card p-4">
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Users className="h-4 w-4" />
              扫码加我
            </div>

            <div className="flex flex-wrap items-start gap-4">
              {qr && !qrBroken ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={qr}
                  alt="产品方微信二维码"
                  onError={() => setQrBroken(true)}
                  className="h-40 w-40 rounded-lg border border-border/70 bg-background object-contain"
                />
              ) : (
                <div className="flex h-40 w-40 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border/70 bg-muted/30 p-2 text-center text-[11px] text-muted-foreground">
                  <TriangleAlert className="h-4 w-4" />
                  <span>二维码图片缺失</span>
                  <span className="text-[10px] text-muted-foreground/70">
                    请将二维码放入 public/ 或修正 NEXT_PUBLIC_CONTACT_QR
                  </span>
                </div>
              )}
              <div className="min-w-0 flex-1 space-y-2">
                <div className="text-xs text-foreground/80">
                  扫码加我个人微信，备注来意（如「老马AI工作台」「素材库」或「企业交付」），
                  我拉你进对应微信群，可获取使用答疑、新版本通知与优惠信息。
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-border/70 bg-muted/30 p-4 text-xs text-muted-foreground">
            二维码尚未配置（构建时未设置
            <code className="mx-1 font-mono">NEXT_PUBLIC_CONTACT_QR</code>
            ）。
          </div>
        )}

        {/* 群邀请链接：可选口子。现在主流做法是「扫码 + 备注来意 → 人工拉群」，
            没有固定群链接；将来有企业微信群链接时配 NEXT_PUBLIC_CONTACT_GROUP_URL 即可。 */}
        {groupUrl ? (
          <div className="rounded-xl border border-border/70 bg-card p-4">
            <div className="text-xs text-muted-foreground">群邀请链接</div>
            <Button size="sm" asChild className="mt-2">
              <a href={groupUrl} target="_blank" rel="noopener noreferrer">
                <QrCode className="mr-1.5 h-4 w-4" />
                打开群链接
              </a>
            </Button>
          </div>
        ) : null}

        {CONTACT_NOTICE.trim() ? (
          <div className="rounded-lg border border-border/70 bg-muted/30 p-2.5 text-xs text-muted-foreground">
            {CONTACT_NOTICE}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

export default ContactCard
