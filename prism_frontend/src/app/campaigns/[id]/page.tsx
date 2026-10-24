"use client"

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useParams, useRouter } from "next/navigation"
import { ArrowLeft, Calendar, Users, FileVideo, Play, Pause, Plus, Loader2, Trash2, CheckCircle2, XCircle, Clock, AlertCircle, Package } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ScrollArea } from "@/components/ui/scroll-area"
import { useToast } from "@/components/ui/use-toast"
import { format } from "date-fns"

export default function CampaignDetailPage() {
    const params = useParams()
    const router = useRouter()
    const { toast } = useToast()
    const campaignId = params.id as string
    const queryClient = useQueryClient()

    // 获取计划详情
    const { data: campaignRes, isLoading: campaignLoading } = useQuery({
        queryKey: ["campaign", campaignId],
        queryFn: async () => {
            const res = await fetch(`/api/v1/campaigns/${campaignId}`)
            if (!res.ok) throw new Error("Failed to fetch campaign")
            return res.json()
        },
    })

    // 获取任务列表
    const { data: tasksRes, isLoading: tasksLoading } = useQuery({
        queryKey: ["campaign-tasks", campaignId],
        queryFn: async () => {
            const res = await fetch(`/api/v1/campaigns/${campaignId}/tasks`)
            if (!res.ok) throw new Error("Failed to fetch tasks")
            return res.json()
        },
    })

    const campaign = campaignRes?.result?.plan
    const tasks = (tasksRes?.result?.items as any[]) || []

    // L3-1：关联发布任务（向导提交，带 campaign_id 透传写入 publish_tasks）
    const { data: publishTasksRes } = useQuery({
        queryKey: ["campaign-publish-tasks", campaignId],
        queryFn: async () => {
            const res = await fetch(`/api/v1/campaigns/${campaignId}/publish-tasks`)
            if (!res.ok) return { result: { items: [] as any[], count: 0 } }
            return res.json()
        },
    })
    const publishTasks = (publishTasksRes?.result?.items as any[]) || []

    // 执行计划
    const executeMutation = useMutation({
        mutationFn: async (id: string) => {
            const res = await fetch(`/api/v1/campaigns/${id}/execute`, { method: "POST" })
            if (!res.ok) throw new Error("执行失败")
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["campaign", campaignId] })
            toast({ title: "计划已执行" })
        },
        onError: (error: Error) => {
            toast({ variant: "destructive", title: "执行失败", description: error.message })
        },
    })

    // 暂停 / 恢复计划
    const toggleStatusMutation = useMutation({
        mutationFn: async ({ id, action }: { id: string; action: "pause" | "resume" }) => {
            const res = await fetch(`/api/v1/campaigns/${id}/${action}`, { method: "POST" })
            if (!res.ok) throw new Error(action === "pause" ? "暂停失败" : "恢复失败")
            return res.json()
        },
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["campaign", campaignId] })
            toast({ title: "状态已更新" })
        },
        onError: (error: Error) => {
            toast({ variant: "destructive", title: "操作失败", description: error.message })
        },
    })

    // 删除计划
    const deleteMutation = useMutation({
        mutationFn: async (id: string) => {
            const res = await fetch(`/api/v1/campaigns/${id}`, { method: "DELETE" })
            if (!res.ok) throw new Error("删除失败")
            return res.json()
        },
        onSuccess: () => {
            toast({ title: "计划已删除" })
            router.push("/campaigns")
        },
        onError: (error: Error) => {
            toast({ variant: "destructive", title: "删除失败", description: error.message })
        },
    })

    if (campaignLoading || !campaign) {
        return <div className="p-10 text-center">加载中...</div>
    }

    const platformLabels: Record<string, string> = {
        douyin: "抖音",
        kuaishou: "快手",
        xiaohongshu: "小红书",
        bilibili: "B站",
        channels: "视频号",
    }

    // 与列表页保持一致的状态文案
    const statusLabels: Record<string, string> = {
        draft: "草稿",
        running: "运行中",
        paused: "已暂停",
        finished: "已完成",
    }

    // Group tasks by platform
    const tasksByPlatform = tasks.reduce((acc: any, task: any) => {
        const p = task.platform
        if (!acc[p]) acc[p] = []
        acc[p].push(task)
        return acc
    }, {})

    const platforms = Object.keys(tasksByPlatform)

    const getStatusIcon = (status: string) => {
        switch (status) {
            case 'finished': return <CheckCircle2 className="w-4 h-4 text-foreground" />
            case 'failed': return <XCircle className="w-4 h-4 text-foreground" />
            case 'running': return <Play className="w-4 h-4 text-foreground animate-pulse" />
            case 'pending': return <Clock className="w-4 h-4 text-muted-foreground" />
            default: return <AlertCircle className="w-4 h-4 text-foreground" />
        }
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex flex-wrap items-center gap-4">
                <Button variant="ghost" size="icon" onClick={() => router.back()} className="rounded-xl">
                    <ArrowLeft className="h-5 w-5" />
                </Button>
                <div className="flex-1">
                    <h1 className="text-3xl font-semibold">{campaign.name}</h1>
                    <div className="flex items-center gap-2 mt-1 text-sm text-muted-foreground">
                        <Badge variant="outline">{statusLabels[campaign.status] || campaign.status}</Badge>
                        <span>{format(new Date(campaign.created_at), "yyyy-MM-dd HH:mm")} 创建</span>
                    </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {/* 任务包构建器入口：选平台/账号/素材/时段后生成投放任务 */}
                    <Button
                        variant="outline"
                        className="rounded-xl border-border/70 bg-popover hover:bg-accent/50"
                        onClick={() => router.push(`/campaigns/${campaignId}/new`)}
                    >
                        <Plus className="mr-2 h-4 w-4" />
                        创建任务包
                    </Button>
                    {campaign.status === "draft" && (
                        <Button
                            className="rounded-xl"
                            onClick={() => executeMutation.mutate(campaignId)}
                            disabled={executeMutation.isPending}
                        >
                            {executeMutation.isPending ? (
                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            ) : (
                                <Play className="mr-2 h-4 w-4" />
                            )}
                            执行计划
                        </Button>
                    )}
                    {campaign.status === "running" && (
                        <Button
                            variant="outline"
                            className="rounded-xl"
                            onClick={() => toggleStatusMutation.mutate({ id: campaignId, action: "pause" })}
                            disabled={toggleStatusMutation.isPending}
                        >
                            <Pause className="mr-2 h-4 w-4" />
                            暂停投放
                        </Button>
                    )}
                    {campaign.status === "paused" && (
                        <Button
                            variant="outline"
                            className="rounded-xl"
                            onClick={() => toggleStatusMutation.mutate({ id: campaignId, action: "resume" })}
                            disabled={toggleStatusMutation.isPending}
                        >
                            <Play className="mr-2 h-4 w-4" />
                            恢复投放
                        </Button>
                    )}
                    <Button
                        variant="ghost"
                        size="icon"
                        className="rounded-xl text-destructive hover:bg-destructive/10 hover:text-destructive"
                        onClick={() => deleteMutation.mutate(campaignId)}
                        disabled={deleteMutation.isPending}
                        title="删除计划"
                    >
                        {deleteMutation.isPending ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <Trash2 className="h-4 w-4" />
                        )}
                    </Button>
                </div>
            </div>

            {/* Stats Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <Card>
                    <CardContent className="pt-6">
                        <div className="text-2xl font-bold">{tasks.length}</div>
                        <div className="text-xs text-muted-foreground">总任务数</div>
                    </CardContent>
                </Card>
                <Card>
                    <CardContent className="pt-6">
                        <div className="text-2xl font-bold text-foreground">
                            {tasks.filter((t: any) => t.status === 'finished').length}
                        </div>
                        <div className="text-xs text-muted-foreground">已完成</div>
                    </CardContent>
                </Card>
                <Card>
                    <CardContent className="pt-6">
                        <div className="text-2xl font-bold text-foreground">
                            {tasks.filter((t: any) => t.status === 'running' || t.status === 'pending').length}
                        </div>
                        <div className="text-xs text-muted-foreground">进行中/等待</div>
                    </CardContent>
                </Card>
                <Card>
                    <CardContent className="pt-6">
                        <div className="text-2xl font-bold text-foreground">
                            {tasks.filter((t: any) => t.status === 'failed').length}
                        </div>
                        <div className="text-xs text-muted-foreground">失败</div>
                    </CardContent>
                </Card>
            </div>

            {/* Task List */}
            <Card>
                <CardHeader>
                    <CardTitle>任务详情</CardTitle>
                    <CardDescription>按平台查看生成的任务执行情况</CardDescription>
                </CardHeader>
                <CardContent>
                    {platforms.length === 0 ? (
                        <div className="text-center py-10 text-muted-foreground">暂无任务</div>
                    ) : (
                        <Tabs defaultValue={platforms[0]}>
                            <TabsList>
                                {platforms.map(p => (
                                    <TabsTrigger key={p} value={p}>
                                        {platformLabels[p] || p} ({tasksByPlatform[p].length})
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                            {platforms.map(p => (
                                <TabsContent key={p} value={p} className="mt-4">
                                    <div className="border rounded-md">
                                        <div className="bg-muted/50 px-4 py-3 text-sm font-medium grid grid-cols-6 gap-4">
                                            <div>状态</div>
                                            <div className="col-span-2">账号</div>
                                            <div className="col-span-2">素材</div>
                                            <div>最后更新</div>
                                        </div>
                                        <ScrollArea className="h-[500px]">
                                            {tasksByPlatform[p].map((task: any) => (
                                                <div key={task.task_id} className="px-4 py-3 text-sm grid grid-cols-6 gap-4 border-b last:border-0 hover:bg-muted/30 items-center">
                                                    <div className="flex items-center gap-2">
                                                        {getStatusIcon(task.status)}
                                                        <span className="capitalize">{task.status}</span>
                                                    </div>
                                                    <div className="col-span-2 truncate font-medium">
                                                        {task.account_id}
                                                    </div>
                                                    <div className="col-span-2 truncate text-muted-foreground">
                                                        {task.material_id}
                                                    </div>
                                                    <div className="text-xs text-muted-foreground">
                                                        {task.updated_at ? format(new Date(task.updated_at), "MM-dd HH:mm") : "-"}
                                                    </div>
                                                    {task.error_msg && (
                                                        <div className="col-span-6 text-xs text-foreground mt-1 bg-popover p-2 rounded">
                                                            错误: {task.error_msg}
                                                        </div>
                                                    )}
                                                </div>
                                            ))}
                                        </ScrollArea>
                                    </div>
                                </TabsContent>
                            ))}
                        </Tabs>
                    )}
                </CardContent>
            </Card>

            {publishTasks.length > 0 && (
              <Card className="rounded-2xl border border-border/70 bg-card">
                <CardHeader className="flex flex-col space-y-2 p-6 pb-4">
                  <CardTitle className="flex items-center gap-2 text-foreground">
                    <Package className="h-5 w-5" />
                    向导关联发布任务
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    以下发布任务通过「矩阵发布向导」勾选本活动后提交，已自动关联 campaign_id。
                  </p>
                </CardHeader>
                <CardContent className="p-6 pt-2">
                  <div className="overflow-x-auto rounded-xl border border-border/70">
                    <table className="w-full text-sm">
                      <thead className="bg-muted/30">
                        <tr>
                          <th className="px-4 py-2.5 text-left text-muted-foreground">状态</th>
                          <th className="px-4 py-2.5 text-left text-muted-foreground">标题</th>
                          <th className="px-4 py-2.5 text-left text-muted-foreground">平台</th>
                          <th className="px-4 py-2.5 text-left text-muted-foreground">账号</th>
                          <th className="px-4 py-2.5 text-left text-muted-foreground">素材</th>
                          <th className="px-4 py-2.5 text-left text-muted-foreground">创建时间</th>
                        </tr>
                      </thead>
                      <tbody>
                        {publishTasks.map((t: any) => (
                          <tr key={t.celery_task_id || t.task_id} className="border-t border-border/50 hover:bg-muted/20">
                            <td className="px-4 py-2">
                              <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${
                                t.status === "success" ? "bg-green-500/10 text-green-600" :
                                t.status === "failed" ? "bg-red-500/10 text-red-600" :
                                t.status === "cancelled" ? "bg-gray-500/10 text-gray-500" :
                                "bg-blue-500/10 text-blue-600"
                              }`}>{t.status || "pending"}</span>
                            </td>
                            <td className="px-4 py-2 truncate max-w-[200px]" title={t.title}>{t.title || "-"}</td>
                            <td className="px-4 py-2">{t.platform || "-"}</td>
                            <td className="px-4 py-2 truncate">{t.account_id || "-"}</td>
                            <td className="px-4 py-2 truncate">{t.material_id || "-"}</td>
                            <td className="px-4 py-2 text-xs text-muted-foreground">
                              {t.created_at ? new Date(t.created_at).toLocaleString("zh-CN", { hour12: false }) : "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
    )
}
