"use client"

import * as React from "react"
import Image from "next/image"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { AnimatePresence, motion } from "framer-motion"
import {
  BarChart3,
  ChevronsLeft,
  ChevronDown,
  CalendarDays,
  ClipboardList,
  Fingerprint,
  FolderKanban,
  Globe,
  Image as ImageIcon,
  LayoutDashboard,
  LayoutGrid,
  Settings,
  UsersRound,
  Video,
  Boxes,
  Network,
  MessageCircle,
  NotebookPen,
  PersonStanding,
  Scissors,
  Sparkles,
  Palette,
  Inbox,
  Layers,
  FolderOpen,
  Hammer,
  Film,
  TrendingUp,
  Send,
  ListChecks,
  Package,
  ShieldCheck,
  Newspaper,
} from "lucide-react"
import { externalModules } from "@/lib/external-modules"

import { Button } from "@/components/ui/button"
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import { HermesLogoIcon } from "@/components/hermes-logo-icon"
import { PlanBadge } from "@/components/layout/plan-badge"

import { cn } from "@/lib/utils"

const DouyinIcon = ({ className }: { className?: string }) => (
  <div className={cn("relative flex shrink-0 items-center justify-center", className)}>
    <Image src="/douYin.svg" alt="Douyin" width={16} height={16} className="object-contain" />
  </div>
)

const BilibiliIcon = ({ className }: { className?: string }) => (
  <div className={cn("relative flex shrink-0 items-center justify-center", className)}>
    <Image src="/bilibili.svg" alt="Bilibili" width={16} height={16} className="object-contain" />
  </div>
)

const KuaishouIcon = ({ className }: { className?: string }) => (
  <div className={cn("relative flex shrink-0 items-center justify-center", className)}>
    <Image src="/kuaiShou.svg" alt="Kuaishou" width={16} height={16} className="object-contain" />
  </div>
)

const XhsIcon = ({ className }: { className?: string }) => (
  <div className={cn("relative flex shrink-0 items-center justify-center", className)}>
    <Image src="/xiaoHongShu.svg" alt="XHS" width={16} height={16} className="object-contain" />
  </div>
)

const ChannelsIcon = ({ className }: { className?: string }) => (
  <div className={cn("relative flex shrink-0 items-center justify-center", className)}>
    <Image src="/shiPingHao.svg" alt="Channels" width={16} height={16} className="object-contain" />
  </div>
)

const TikTokIcon = ({ className }: { className?: string }) => (
  <div className={cn("relative flex shrink-0 items-center justify-center", className)}>
    <Image src="/Tiktok.svg" alt="TikTok" width={16} height={16} className="object-contain" />
  </div>
)

const YoutubeIcon = ({ className }: { className?: string }) => (
  <div className={cn("relative flex shrink-0 items-center justify-center", className)}>
    <Image src="/youtube.svg" alt="YouTube" width={16} height={16} className="object-contain" />
  </div>
)

interface NavItem {
  label: string
  href?: string
  // 允许传 lucide 图标(SVG props)或自定义图标组件(仅需 className),
  // 显式声明可接受的最小 props 集合避免 ElementType 泛型推断出错。
  icon: React.ComponentType<{ className?: string; suppressHydrationWarning?: boolean }>
  disabled?: boolean
  external?: boolean
  children?: NavItem[]
}

interface NavSection {
  label: string
  items: NavItem[]
}

const externalNavSection: NavSection = {
  label: "扩展",
  items: externalModules.map((module): NavItem => ({
    label: module.label,
    href: module.href,
    icon: module.icon,
  })),
}

const navSections: NavSection[] = [
  {
    label: "概览",
    items: [
      { label: "仪表盘", href: "/", icon: LayoutDashboard },
      { label: "快速开始", href: "/guide", icon: Sparkles },
    ],
  },
  {
    label: "资源",
    items: [
      { label: "账号管理", href: "/account", icon: UsersRound },
      { label: "素材管理", href: "/materials", icon: FolderKanban },
      { label: "代理管理", href: "/ip-pool", icon: Globe },
      { label: "代理网关", href: "/persona-proxy", icon: Network },
      { label: "Persona", href: "/persona", icon: Fingerprint },
    ],
  },
  {
    label: "内容",
    items: [
      { label: "选题库", href: "/ideas", icon: NotebookPen },
      { label: "趋势热榜", href: "/trends", icon: TrendingUp },
      { label: "内容拆解", href: "/breakdown", icon: Scissors },
      { label: "账号画像", href: "/profile", icon: PersonStanding },
      { label: "内容库", href: "/easel-content", icon: FolderOpen },
      { label: "收件箱", href: "/easel-inbox", icon: Inbox },
      { label: "创作工作台", href: "/easel-workbench", icon: Palette },
      { label: "创作工坊", href: "/workshop", icon: Hammer },
      { label: "CMS", href: "/cms", icon: Newspaper },
    ],
  },
  {
    label: "生成",
    items: [
      { label: "AI 生图", href: "/fusion/image-studio", icon: ImageIcon },
      { label: "视频流水线", href: "/video-pipeline", icon: Film },
      { label: "图片编辑器", href: "/tools/image-editor", icon: Scissors },
    ],
  },
  {
    label: "分发",
    items: [
      { label: "矩阵发布", href: "/publish/matrix", icon: LayoutGrid },
      { label: "发布中心", href: "/publish", icon: Send },
      { label: "发布任务", href: "/tasks/publish", icon: ListChecks },
      { label: "分发记录", href: "/tasks/distribution", icon: Globe },
      { label: "营销活动", href: "/campaigns", icon: Package },
      { label: "排期日历", href: "/calendar", icon: CalendarDays },
      { label: "审核队列", href: "/review", icon: ShieldCheck },
      { label: "任务管理", href: "/tasks", icon: ClipboardList },
    ],
  },
  {
    label: "数据",
    items: [
      { label: "数据中心", href: "/analytics", icon: BarChart3 },
      { label: "趋势分析", href: "/analytics/trends", icon: TrendingUp },
      {
        label: "视频数据",
        href: "/analytics/videos",
        icon: Video,
        children: [
          { label: "抖音", href: "/analytics/videos/douyin", icon: DouyinIcon },
          { label: "B 站", href: "/analytics/videos/bilibili", icon: BilibiliIcon },
          { label: "快手", href: "/analytics/videos/kuaishou", icon: KuaishouIcon },
          { label: "小红书", href: "/analytics/videos/xiaohongshu", icon: XhsIcon },
          { label: "视频号", href: "/analytics/videos/channels", icon: ChannelsIcon },
          { label: "TikTok", href: "/analytics/videos/tiktok", icon: TikTokIcon },
          { label: "YouTube", href: "/analytics/videos/youtube", icon: YoutubeIcon },
        ],
      },
    ],
  },
  {
    label: "智能",
    items: [
      {
        label: "Hermes Agent",
        href: "/ai-agent",
        icon: HermesLogoIcon,
        children: [
          { label: "Agent 控制台", href: "/ai-agent", icon: HermesLogoIcon },
          { label: "提示词配置", href: "/ai-agent/prompts", icon: NotebookPen },
          { label: "运行设置", href: "/ai-agent/settings", icon: Settings },
        ],
      },
      { label: "HermesChat", href: "/hermes-chat", icon: MessageCircle },
      { label: "AI 对话", href: "/chat", icon: MessageCircle },
      { label: "技能库", href: "/skills", icon: Layers },
    ],
  },
  {
    label: "AI-Fusion",
    items: [
      { label: "融合中心", href: "/fusion", icon: Sparkles },
      { label: "风格库", href: "/fusion/styles", icon: Palette },
      { label: "内容审查", href: "/fusion/moderation", icon: ShieldCheck },
      { label: "融合分析", href: "/fusion/analytics", icon: BarChart3 },
      { label: "融合配置", href: "/fusion/config", icon: Settings },
      { label: "模型市场", href: "/fusion/model-market", icon: Boxes },
      { label: "供应商配置", href: "/fusion/providers", icon: Network },
    ],
  },
  {
    label: "开发者工具",
    items: [
      { label: "工具中心", href: "/tools", icon: Boxes },
      { label: "演示控制台", href: "/dashboard-demo", icon: LayoutGrid },
    ],
  },
  {
    label: "系统",
    items: [
      { label: "系统设置", href: "/settings", icon: Settings },
    ],
  },
]

// 外置模块（external-modules.ts）里已经被上面的原生分组覆盖的条目不再重复展示，
// 避免同一个页面在侧边栏出现两次。
const nativeHrefs = new Set<string>()
for (const section of navSections) {
  for (const item of section.items) {
    if (item.href) nativeHrefs.add(item.href)
    for (const child of item.children ?? []) {
      if (child.href) nativeHrefs.add(child.href)
    }
  }
}
const dedupedExternalItems = externalNavSection.items.filter(
  (item) => !item.href || !nativeHrefs.has(item.href)
)
if (dedupedExternalItems.length > 0) {
  navSections.push({ label: externalNavSection.label, items: dedupedExternalItems })
}

interface SidebarProps extends React.HTMLAttributes<HTMLDivElement> {
  collapsed: boolean
  setCollapsed: (collapsed: boolean) => void
  showCollapseToggle?: boolean
  onNavigate?: () => void
}

export function SidebarNew({
  className,
  collapsed,
  setCollapsed,
  showCollapseToggle = true,
  onNavigate,
}: SidebarProps) {
  const pathname = usePathname()

  return (
    <div className="relative flex">
      <motion.aside
        initial={false}
        animate={{ width: collapsed ? 64 : 240 }}
        transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
        className={cn("relative flex h-screen flex-col border-r border-border bg-glass-strong text-foreground", className)}
      >
        <div className="flex h-[52px] items-center justify-between border-b border-border px-4">
          <AnimatePresence mode="wait">
            {!collapsed ? (
              <motion.div
                key="logo-full"
                initial={false}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -20 }}
                transition={{ duration: 0.3 }}
                className="flex items-center gap-3"
              >
                <img src="/logo.png" alt="老马AI研习社" className="h-8 w-8 rounded object-contain" />
                <span className="text-base font-bold tracking-tight">老马AI研习社</span>
              </motion.div>
            ) : (
              <motion.div
                key="logo-icon"
                initial={false}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.8 }}
                transition={{ duration: 0.3 }}
                className="flex items-center justify-center"
              >
                <img src="/logo.png" alt="老马AI研习社" className="h-8 w-8 rounded object-contain" />
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {!collapsed && (
          <div className="border-b border-border px-3 py-2">
            <button
              type="button"
              className="flex h-8 w-full items-center justify-between border border-border bg-background px-2.5 text-left text-[11px] text-foreground/70 transition hover:bg-accent hover:text-foreground"
            >
              <span className="truncate">this workspace (default)</span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-foreground/40" />
            </button>
          </div>
        )}

        <ScrollArea className="scrollbar-none flex-1 px-2 py-3">
          <nav className="space-y-6">
            {navSections.map((section) => (
              <div key={section.label} className="space-y-1">
                <AnimatePresence mode="wait">
                  {!collapsed && (
                    <motion.div
                      key={`section-${section.label}`}
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.2 }}
                    >
                      <h3 className="mb-2 px-3 text-[10px] font-medium uppercase tracking-[0.18em] text-foreground/35">
                        {section.label}
                      </h3>                    </motion.div>
                  )}
                </AnimatePresence>

                <div className="space-y-1">
                  {section.items.map((item) => {
                    const Icon = item.icon
                    const isActive = item.href ? pathname === item.href : false
                    const hasChildren = (item.children?.length ?? 0) > 0

                    if (hasChildren) {
                      // 通用展开判定：当前路径落在该分组任一子项前缀下就自动展开，
                      // 不再为每个分组硬编码路径。
                      const shouldOpen = item.href
                        ? pathname === item.href || pathname.startsWith(`${item.href}/`)
                        : false
                      const triggerContent = (
                        <div
                          className={cn(
                            "group relative flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                            "text-foreground/70 hover:bg-accent hover:text-accent-foreground",
                          )}
                        >
                          <Icon className="relative h-5 w-5 shrink-0" suppressHydrationWarning />
                          <AnimatePresence mode="wait">
                            {!collapsed && (
                              <motion.span
                                key={`text-${item.label}`}
                                initial={false}
                                animate={{ opacity: 1, width: "auto" }}
                                exit={{ opacity: 0, width: 0 }}
                                transition={{ duration: 0.2 }}
                                className="relative overflow-hidden whitespace-nowrap"
                              >
                                {item.label}
                              </motion.span>
                            )}
                          </AnimatePresence>
                          {!collapsed && <ChevronDown className="ml-auto h-4 w-4 text-foreground/40" />}
                        </div>
                      )

                      if (collapsed) {
                        return (
                          <TooltipProvider key={item.label} delayDuration={0}>
                            <Tooltip>
                              <TooltipTrigger asChild>{triggerContent}</TooltipTrigger>
                              <TooltipContent side="right" className="border-border bg-background text-foreground">
                                {item.label}
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        )
                      }

                      return (
                        <Collapsible key={item.label} defaultOpen={shouldOpen}>
                          <CollapsibleTrigger asChild>{triggerContent}</CollapsibleTrigger>
                          <CollapsibleContent className="space-y-1 pl-4 pt-1">
                            {item.children?.map((child) => {
                              const ChildIcon = child.icon
                              const childActive = pathname === child.href
                              return (
                                <Link
                                  key={child.label}
                                  href={child.href || "#"}
                                  onClick={() => onNavigate?.()}
                                  className={cn(
                                    "flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-all duration-200",
                                    childActive
                                      ? "bg-accent text-foreground"
                                      : "text-foreground/60 hover:bg-accent hover:text-accent-foreground",
                                  )}
                                >
                                  <ChildIcon
                                    className={cn(
                                      "h-4 w-4 shrink-0 transition-colors",
                                      childActive ? "text-primary" : "text-foreground/50 group-hover:text-foreground"
                                    )}
                                    suppressHydrationWarning
                                  />
                                  <span className="truncate">{child.label}</span>
                                </Link>
                              )
                            })}
                          </CollapsibleContent>
                        </Collapsible>
                      )
                    }

                    const itemContent = (
                      <Link
                        href={item.href || "#"}
                        onClick={() => onNavigate?.()}
                        className={cn(
                          "group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200",
                            isActive
                            ? "bg-accent text-foreground"
                            : "text-foreground/70 hover:bg-accent hover:text-accent-foreground",
                        )}
                      >
                        {isActive && (
                          <span className="absolute left-0 top-1/2 h-5 w-[2px] -translate-y-1/2 bg-primary" />
                        )}
                        <Icon
                          className={cn(
                            "relative h-5 w-5 shrink-0 transition-colors",
                            isActive ? "text-primary" : "text-foreground/60 group-hover:text-foreground"
                          )}
                          suppressHydrationWarning
                        />
                        <AnimatePresence mode="wait">
                          {!collapsed && (
                            <motion.span
                              key={`item-${item.label}`}
                              initial={false}
                              animate={{ opacity: 1, width: "auto" }}
                              exit={{ opacity: 0, width: 0 }}
                              transition={{ duration: 0.2 }}
                              className="overflow-hidden whitespace-nowrap"
                            >
                              {item.label}
                            </motion.span>
                          )}
                        </AnimatePresence>
                      </Link>
                    )

                    if (collapsed) {
                      return (
                        <TooltipProvider key={item.label} delayDuration={0}>
                          <Tooltip>
                            <TooltipTrigger asChild>{itemContent}</TooltipTrigger>
                            <TooltipContent side="right" className="border-border bg-background text-foreground">
                              {item.label}
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      )
                    }

                    return <React.Fragment key={item.label}>{itemContent}</React.Fragment>
                  })}
                </div>
              </div>
            ))}
          </nav>
        </ScrollArea>

        {/* Open Core · 套餐徽标（Community / Pro + 配额 + 升级按钮） */}
        <div className="border-t border-border/80 p-3">
          <PlanBadge collapsed={collapsed} />
        </div>

        {showCollapseToggle && (
          <div className="border-t border-border/80 p-3">
            {!collapsed && (
              <div className="mb-3 flex items-center justify-between px-2 text-[10px] uppercase tracking-[0.16em] text-foreground/35">
                <span>System</span>
                <span className="flex items-center gap-1.5 normal-case tracking-normal text-emerald-400/80">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" /> Online
                </span>
              </div>
            )}
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setCollapsed(!collapsed)}
              className="h-10 w-10 rounded-xl text-foreground/70 hover:bg-accent hover:text-accent-foreground"
            >
              <motion.div animate={{ rotate: collapsed ? 180 : 0 }} transition={{ duration: 0.2 }}>
                <ChevronsLeft className="h-5 w-5" />
              </motion.div>
            </Button>
          </div>
        )}
      </motion.aside>
    </div>
  )
}
