"use client"

import { useCallback, useEffect, useState } from "react"
import {
    Download,
    ExternalLink,
    Inbox,
    Loader2,
    PackagePlus,
    RefreshCw,
    Sparkles,
} from "lucide-react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useToast } from "@/components/ui/use-toast"
import {
    CreateCampaignDialog,
    type CampaignPrefillValues,
} from "@/components/campaigns/create-campaign-dialog"

interface EaselDraft {
    project: string
    path: string
    title: string
    summary: string
    platform: string
    kind: string
    status: string
    tags: string[]
    cover: string
    deliverables: string[]
    importable_deliverables: string[]
    mtime: number
    imported: boolean
}

interface ImportResult {
    already_imported: boolean
    project: string
    material_ids: number[]
    suggested_platforms?: string[]
    campaign_prefill?: { name?: string; remark?: string }
}

// Easel 平台名 → 老马AI工作台 投放平台 id
const PLATFORM_MAP: Record<string, string> = {
    xiaohongshu: "xiaohongshu",
    douyin: "douyin",
    kuaishou: "kuaishou",
    bilibili: "bilibili",
    channels: "channels",
    wechat_channels: "channels",
    shipinhao: "channels",
}

const PLATFORM_LABELS: Record<string, string> = {
    xiaohongshu: "小红书",
    douyin: "抖音",
    kuaishou: "快手",
    bilibili: "B站",
    channels: "视频号",
    zhihu: "知乎",
    "wechat-oa": "公众号",
}

const PRISM_PLATFORMS = ["douyin", "kuaishou", "xiaohongshu", "bilibili", "channels", "tiktok", "youtube"]

function mediaUrl(path: string) {
    return `/api/v1/easel/media/${path}`
}

export default function EaselInboxPage() {
    const { toast } = useToast()
    const [drafts, setDrafts] = useState<EaselDraft[]>([])
    const [loading, setLoading] = useState(true)
    const [easelOnline, setEaselOnline] = useState<boolean | null>(null)
    const [starting, setStarting] = useState(false)
    const [importing, setImporting] = useState<string | null>(null)
    const [importedMap, setImportedMap] = useState<Record<string, ImportResult>>({})
    const [dialogOpen, setDialogOpen] = useState(false)
    const [prefill, setPrefill] = useState<CampaignPrefillValues | null>(null)

    const loadStatus = useCallback(async () => {
        try {
            const res = await fetch("/api/v1/easel/status", { cache: "no-store" })
            const data = await res.json()
            const result = data?.result
            const online = Boolean(result?.running && result?.web_api_online)
            setEaselOnline(online)
            return online
        } catch {
            setEaselOnline(false)
            return false
        }
    }, [])

    const loadDrafts = useCallback(async () => {
        setLoading(true)
        try {
            const res = await fetch("/api/v1/easel/drafts", { cache: "no-store" })
            const data = await res.json()
            setDrafts(data?.result?.drafts || [])
        } catch {
            setDrafts([])
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        void (async () => {
            const online = await loadStatus()
            if (online) await loadDrafts()
            else setLoading(false)
        })()
    }, [loadStatus, loadDrafts])

    const startEasel = async () => {
        setStarting(true)
        try {
            const res = await fetch("/api/v1/easel/start", { method: "POST" })
            const data = await res.json()
            if (res.ok && data?.result?.web_api_online) {
                toast({ title: "Easel 已启动" })
                setEaselOnline(true)
                await loadDrafts()
            } else {
                toast({ variant: "destructive", title: "Easel 启动失败", description: data?.detail })
            }
        } catch (e) {
            toast({ variant: "destructive", title: "Easel 启动失败", description: String(e) })
        } finally {
            setStarting(false)
        }
    }

    const importDraft = async (draft: EaselDraft) => {
        setImporting(draft.project)
        try {
            const res = await fetch(`/api/v1/easel/drafts/${encodeURIComponent(draft.project)}/import`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
            })
            const data = await res.json()
            if (!res.ok) {
                throw new Error(data?.detail || "导入失败")
            }
            const result = data.result as ImportResult
            setImportedMap((prev) => ({ ...prev, [draft.project]: result }))
            setDrafts((prev) => prev.map((d) => (d.project === draft.project ? { ...d, imported: true } : d)))
            toast({
                title: result.already_imported ? "该稿件已导入过" : "导入成功",
                description: `素材 ID：${result.material_ids.join(", ") || "无"}`,
            })
        } catch (e) {
            toast({ variant: "destructive", title: "导入失败", description: e instanceof Error ? e.message : String(e) })
        } finally {
            setImporting(null)
        }
    }

    const openCreateCampaign = (draft: EaselDraft) => {
        const importResult = importedMap[draft.project]
        const materialIds = (importResult?.material_ids || []).map(String)
        if (materialIds.length === 0) {
            toast({ variant: "destructive", title: "请先导入素材库" })
            return
        }
        const rawPlatforms = importResult?.suggested_platforms?.length
            ? importResult.suggested_platforms
            : draft.platform
                ? [draft.platform]
                : []
        const platforms = rawPlatforms
            .map((p) => PLATFORM_MAP[p] || p)
            .filter((p) => PRISM_PLATFORMS.includes(p))
        setPrefill({
            name: importResult?.campaign_prefill?.name || draft.title,
            remark: importResult?.campaign_prefill?.remark || draft.summary,
            platforms,
            materialIds,
        })
        setDialogOpen(true)
    }

    const refreshAll = useCallback(async () => {
        const online = await loadStatus()
        if (online) await loadDrafts()
    }, [loadStatus, loadDrafts])

    return (
        <div className="min-h-screen">
            <PageHeader
                eyebrow="PUBLISH · EASEL INBOX"
                title="Easel 稿件箱"
                description="从 Easel 创作工作台接收成品稿件，导入素材库后直接创建矩阵投放计划。"
                actions={
                    <Button variant="ghost" onClick={refreshAll} disabled={loading}>
                        <RefreshCw className="h-4 w-4 mr-2" /> 刷新
                    </Button>
                }
            />

            <div className="mx-auto max-w-6xl space-y-5 px-6 py-6">
                {easelOnline === false && (
                    <Card className="border-amber-500/40 bg-amber-500/5 p-5">
                        <div className="flex flex-wrap items-center justify-between gap-3">
                            <div className="space-y-1">
                                <div className="text-sm font-medium">Easel 工作台未运行</div>
                                <div className="text-sm text-muted-foreground">
                                    启动后即可在这里看到 Easel 里做好的稿件。
                                </div>
                            </div>
                            <div className="flex gap-2">
                                <Button onClick={startEasel} disabled={starting}>
                                    {starting ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Sparkles className="h-4 w-4 mr-2" />}
                                    启动 Easel
                                </Button>
                                <Button variant="outline" onClick={() => window.open("http://127.0.0.1:7860", "_blank")}>
                                    <ExternalLink className="h-4 w-4 mr-2" /> 新窗口打开
                                </Button>
                            </div>
                        </div>
                    </Card>
                )}

                {loading ? (
                    <Card className="p-10 text-center text-muted-foreground">
                        <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2" />
                        正在读取 Easel 稿件…
                    </Card>
                ) : drafts.length === 0 ? (
                    <Card className="p-10 text-center">
                        <Inbox className="h-8 w-8 mx-auto mb-3 text-muted-foreground" />
                        <div className="text-sm font-medium">稿件箱是空的</div>
                        <p className="mt-2 text-sm text-muted-foreground">
                            在 Easel 工作台里完成创作后，带标题与成品的稿件会自动出现在这里。
                        </p>
                    </Card>
                ) : (
                    <div className="grid gap-4 md:grid-cols-2">
                        {drafts.map((draft) => {
                            const importResult = importedMap[draft.project]
                            const canCreate = (importResult?.material_ids?.length || 0) > 0
                            return (
                                <Card key={draft.project} className="overflow-hidden">
                                    <div className="aspect-[16/9] w-full overflow-hidden bg-muted">
                                        {draft.cover ? (
                                            // eslint-disable-next-line @next/next/no-img-element
                                            <img
                                                src={mediaUrl(draft.cover)}
                                                alt={draft.title}
                                                className="h-full w-full object-cover"
                                                loading="lazy"
                                            />
                                        ) : (
                                            <div className="flex h-full items-center justify-center text-muted-foreground">
                                                <Inbox className="h-8 w-8" />
                                            </div>
                                        )}
                                    </div>
                                    <CardContent className="space-y-3 p-4">
                                        <div className="flex items-start justify-between gap-2">
                                            <div className="space-y-1 min-w-0">
                                                <div className="truncate text-sm font-semibold">{draft.title}</div>
                                                {draft.summary && (
                                                    <div className="line-clamp-2 text-xs text-muted-foreground">{draft.summary}</div>
                                                )}
                                            </div>
                                            {draft.imported && <Badge variant="secondary" className="shrink-0 text-xs">已导入</Badge>}
                                        </div>

                                        <div className="flex flex-wrap items-center gap-1.5">
                                            {draft.platform && (
                                                <Badge variant="outline" className="text-xs">
                                                    {PLATFORM_LABELS[draft.platform] || draft.platform}
                                                </Badge>
                                            )}
                                            {draft.status && <Badge variant="outline" className="text-xs">{draft.status}</Badge>}
                                            {draft.tags.slice(0, 4).map((tag) => (
                                                <Badge key={tag} variant="outline" className="text-xs">#{tag}</Badge>
                                            ))}
                                            <span className="text-xs text-muted-foreground ml-auto">
                                                {draft.importable_deliverables.length} 个成品文件
                                            </span>
                                        </div>

                                        {importResult && (
                                            <div className="rounded-lg border bg-muted/30 p-2 text-xs text-muted-foreground">
                                                素材 ID：{importResult.material_ids.join(", ") || "无"}
                                            </div>
                                        )}

                                        <div className="flex items-center gap-2">
                                            <Button
                                                size="sm"
                                                variant={draft.imported ? "outline" : "default"}
                                                onClick={() => importDraft(draft)}
                                                disabled={importing === draft.project}
                                            >
                                                {importing === draft.project ? (
                                                    <Loader2 className="h-4 w-4 animate-spin mr-1.5" />
                                                ) : (
                                                    <Download className="h-4 w-4 mr-1.5" />
                                                )}
                                                {draft.imported ? "重新导入" : "导入素材库"}
                                            </Button>
                                            <Button
                                                size="sm"
                                                variant={canCreate ? "default" : "ghost"}
                                                onClick={() => openCreateCampaign(draft)}
                                                disabled={!draft.imported}
                                            >
                                                <PackagePlus className="h-4 w-4 mr-1.5" />
                                                创建投放计划
                                            </Button>
                                            <a
                                                href={`http://127.0.0.1:7860/#outputs/${encodeURIComponent(draft.project)}`}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="ml-auto text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"
                                            >
                                                在 Easel 查看 <ExternalLink className="h-3 w-3" />
                                            </a>
                                        </div>
                                    </CardContent>
                                </Card>
                            )
                        })}
                    </div>
                )}
            </div>

            <CreateCampaignDialog
                open={dialogOpen}
                onOpenChange={setDialogOpen}
                onSuccess={() => {
                    toast({ title: "投放计划已创建" })
                }}
                initialValues={prefill}
            />
        </div>
    )
}
