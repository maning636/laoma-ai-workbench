"use client"

import { useEffect, useState, useCallback } from "react"
import {
  Settings, RefreshCw, Loader2, Save, RotateCcw, ChevronRight, Search,
} from "lucide-react"
import { PageHeader } from "@/components/layout/page-scaffold"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { API_ENDPOINTS } from "@/lib/env"

interface ConfigGroup {
  id: string
  label: string
  description: string
  category: string
  schema_hint: string
  default: any
  value: any
}

const CATEGORY_COLORS: Record<string, string> = {
  "内容审核": "bg-red-100 text-red-700",
  "平台": "bg-blue-100 text-blue-700",
  "热点": "bg-orange-100 text-orange-700",
  "生图": "bg-purple-100 text-purple-700",
  "AI Provider": "bg-indigo-100 text-indigo-700",
  "模型广场": "bg-teal-100 text-teal-700",
  "技能工坊": "bg-pink-100 text-pink-700",
  "认知": "bg-emerald-100 text-emerald-700",
  "数据分析": "bg-cyan-100 text-cyan-700",
}

export default function ConfigPage() {
  const [groups, setGroups] = useState<ConfigGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState("")
  const [editing, setEditing] = useState<string | null>(null)
  const [editValue, setEditValue] = useState("")
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)
  const [error, setError] = useState<string>("")

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/config/groups`)
      const d = await r.json()
      setGroups(d.groups || [])
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const openEdit = (g: ConfigGroup) => {
    setEditing(g.id)
    setEditValue(JSON.stringify(g.value, null, 2))
    setError("")
  }

  const closeEdit = () => {
    setEditing(null)
    setEditValue("")
    setError("")
  }

  const saveEdit = async () => {
    if (!editing) return
    let parsed: any
    try {
      parsed = JSON.parse(editValue)
    } catch {
      setError("JSON 格式无效")
      return
    }
    setSaving(true)
    try {
      await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/config/${editing}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: parsed }),
      })
      setSaved(editing)
      setTimeout(() => setSaved(null), 1500)
      closeEdit()
      load()
    } finally {
      setSaving(false)
    }
  }

  const resetConfig = async (id: string) => {
    await fetch(`${API_ENDPOINTS.base}/api/v1/fusion/config/${id}`, { method: "DELETE" })
    load()
  }

  useEffect(() => { load() }, [load])

  const filtered = groups.filter((g) =>
    !filter ||
    g.label.includes(filter) ||
    g.id.includes(filter) ||
    g.category.includes(filter) ||
    g.description.includes(filter)
  )

  const categories = Array.from(new Set(groups.map((g) => g.category)))

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="min-h-screen">
      <PageHeader
        eyebrow="FUSION · P1"
        title="配置中心"
        description="20 组前台可编辑配置，独立 JSON 持久化，Railway-vol 兼容"
        actions={<Button onClick={load}><RefreshCw className="h-4 w-4 mr-2" />刷新</Button>}
      />

      <div className="mx-auto max-w-6xl space-y-4 px-6 py-6">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-2 h-4 w-4 text-muted-foreground" />
            <Input
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              placeholder="搜索配置..."
              className="pl-8"
            />
          </div>
          <Badge variant="secondary">{filtered.length} / {groups.length}</Badge>
        </div>

        {categories.map((cat) => {
          const catGroups = filtered.filter((g) => g.category === cat)
          if (catGroups.length === 0) return null
          return (
            <div key={cat} className="space-y-2">
              <div className="flex items-center gap-2">
                <span className={`text-xs font-medium px-2 py-0.5 rounded ${CATEGORY_COLORS[cat] || "bg-gray-100 text-gray-700"}`}>{cat}</span>
                <span className="text-xs text-muted-foreground">({catGroups.length})</span>
              </div>
              <div className="grid gap-2">
                {catGroups.map((g) => (
                  <Card key={g.id} className="border">
                    <CardContent className="p-3">
                      {editing === g.id ? (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between">
                            <div className="text-sm font-medium">{g.label} <code className="text-xs text-muted-foreground ml-2">{g.id}</code></div>
                            <div className="flex gap-1">
                              <Button size="sm" variant="ghost" onClick={closeEdit}>取消</Button>
                              <Button size="sm" onClick={saveEdit} disabled={saving}>
                                {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3 mr-1" />}
                                保存
                              </Button>
                            </div>
                          </div>
                          <div className="text-xs text-muted-foreground">
                            Schema: {g.schema_hint}
                          </div>
                          <Textarea
                            value={editValue}
                            onChange={(e) => setEditValue(e.target.value)}
                            className="font-mono text-xs min-h-[160px]"
                          />
                          {error && <div className="text-xs text-red-500">{error}</div>}
                        </div>
                      ) : (
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-sm font-medium">{g.label}</span>
                              <code className="text-xs text-muted-foreground">{g.id}</code>
                              {saved === g.id && (
                                <Badge className="bg-green-100 text-green-700">已保存</Badge>
                              )}
                            </div>
                            <div className="text-xs text-muted-foreground mt-0.5">{g.description}</div>
                            <div className="text-xs text-muted-foreground mt-1 truncate">
                              当前值: {JSON.stringify(g.value)}
                            </div>
                          </div>
                          <div className="flex gap-1 shrink-0">
                            <Button size="sm" variant="outline" onClick={closeEdit}><ChevronRight className="h-3 w-3 mr-1" />编辑</Button>
                            <Button size="sm" variant="ghost" onClick={() => resetConfig(g.id)} title="重置为默认">
                              <RotateCcw className="h-3 w-3" />
                            </Button>
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}