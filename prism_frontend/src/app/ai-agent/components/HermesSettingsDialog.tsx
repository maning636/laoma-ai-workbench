"use client"

import { useCallback, useEffect, useState } from "react"
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  FolderOpen,
  Loader2,
  RefreshCw,
  Save,
  Settings2,
  Wand2,
} from "lucide-react"

import { backendBaseUrl } from "@/lib/env"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

// 弹窗内表单状态
interface HermesConfigForm {
  provider: string
  model: string
  api_key: string
  base_url: string
  max_turns: number
}

interface RuntimeInfo {
  workspace_root?: string
  source_path?: string
  config_path?: string
  python_path?: string
  agent_installed?: boolean
  gateway_running?: boolean
  gateway_pid?: number | null
}

export default function HermesSettingsDialog({
  open,
  onOpenChange,
  onApplied,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  onApplied?: (msg: string) => void
}) {
  const [form, setForm] = useState<HermesConfigForm>({
    provider: "custom",
    model: "",
    api_key: "",
    base_url: "",
    max_turns: 12,
  })
  const [workspace, setWorkspace] = useState<string | null>(null)
  const [runtime, setRuntime] = useState<RuntimeInfo | null>(null)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [configured, setConfigured] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setTestResult(null)
    try {
      const base = backendBaseUrl
      const [cfgRes, rtRes] = await Promise.all([
        fetch(`${base}/api/v1/agent/config/hermes`, { cache: "no-store" }),
        fetch(`${base}/api/v1/agent/config/hermes/runtime`, { cache: "no-store" }),
      ])
      const cfg = (await cfgRes.json()).data || {}
      const rt = (await rtRes.json()).data || {}

      setConfigured(Boolean(cfg?.is_configured))
      if (cfg?.is_configured) {
        setForm({
          provider: cfg.provider || "custom",
          model: cfg.model || "",
          api_key: cfg.api_key || "",
          base_url: cfg.base_url || "",
          max_turns: cfg.max_turns || 12,
        })
      }
      setWorkspace(rt.workspace_root || null)
      setRuntime(rt)
    } catch (e) {
      console.error("加载 Hermes 配置失败", e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) void load()
  }, [open, load])

  const save = useCallback(async () => {
    if (!form.model.trim()) {
      setTestResult({ ok: false, message: "请填写模型名" })
      return
    }
    setSaving(true)
    setTestResult(null)
    try {
      const res = await fetch("/api/v1/agent/config/hermes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          llm: {
            provider: form.provider,
            model: form.model,
            api_key: form.api_key,
            base_url: form.base_url || null,
          },
          runtime: { max_turns: form.max_turns },
        }),
      })
      const payload = await res.json()
      if (!res.ok || !payload?.success) {
        throw new Error(payload?.message || payload?.detail || `HTTP ${res.status}`)
      }
      setTestResult({ ok: true, message: "配置已保存，Agent 已重置" })
      setConfigured(true)
    } catch (e) {
      setTestResult({ ok: false, message: e instanceof Error ? e.message : String(e) })
    } finally {
      setSaving(false)
    }
  }, [form])

  const test = useCallback(async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const res = await fetch("/api/v1/agent/config/hermes/test", { method: "POST" })
      const payload = await res.json()
      const data = payload?.data || {}
      if (payload?.success) {
        setTestResult({ ok: true, message: data.message || "连接正常" })
      } else {
        setTestResult({ ok: false, message: data.message || data.error || "测试失败" })
      }
    } catch (e) {
      setTestResult({ ok: false, message: e instanceof Error ? e.message : String(e) })
    } finally {
      setTesting(false)
    }
  }, [])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <Settings2 className="h-5 w-5 text-primary" />
            <DialogTitle>Hermes Agent 设置</DialogTitle>
          </div>
          <DialogDescription>
            配置 Hermes Agent 的模型连接和工作目录。<code className="px-1 py-0.5 bg-muted rounded text-[11px]">/config/hermes</code>
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 max-h-[60vh] overflow-y-auto pr-1">
          {/* 工作目录 */}
          <div className="rounded-xl border p-3 space-y-2">
            <div className="flex items-center gap-2">
              <FolderOpen className="h-4 w-4 text-primary" />
              <Label className="text-sm font-medium">工作目录</Label>
              {runtime?.agent_installed && <Badge variant="outline" className="text-[10px] gap-1"><CheckCircle2 className="h-3 w-3 text-emerald-500" />已安装</Badge>}
              {runtime?.gateway_running && <Badge variant="outline" className="text-[10px] gap-1"><CheckCircle2 className="h-3 w-3 text-emerald-500" />网关 PID {String(runtime.gateway_pid)}</Badge>}
            </div>
            <div className="flex items-center gap-2">
              <Input value={workspace || "（未设置）"} readOnly className="font-mono text-xs" />
              <Button variant="outline" size="sm" onClick={load} disabled={loading}>
                <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              </Button>
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Hermes Agent 的默认工作区。可通过环境变量 <code className="px-1 bg-muted rounded">PRISM_HERMES_WORKSPACE</code> 在启动时覆盖；本字段仅用于展示当前生效目录。
            </p>
            {runtime?.source_path && (
              <div className="text-[11px] text-muted-foreground truncate">
                Hermes 源码：<span className="font-mono">{runtime.source_path}</span>
              </div>
            )}
          </div>

          <Separator />

          {/* 模型配置 */}
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Wand2 className="h-4 w-4 text-primary" />
              <Label className="text-sm font-medium">模型配置</Label>
              {configured ? (
                <Badge variant="secondary" className="text-[10px]">已配置</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px]">未配置</Badge>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs">Provider</Label>
                <Input
                  value={form.provider}
                  onChange={(e) => setForm((s) => ({ ...s, provider: e.target.value }))}
                  placeholder="custom"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Model</Label>
                <Input
                  value={form.model}
                  onChange={(e) => setForm((s) => ({ ...s, model: e.target.value }))}
                  placeholder="deepseek-v3"
                />
              </div>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs">API Key</Label>
              <Input
                type="password"
                value={form.api_key}
                onChange={(e) => setForm((s) => ({ ...s, api_key: e.target.value }))}
                placeholder="sk-..."
              />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2 space-y-1.5">
                <Label className="text-xs">Base URL</Label>
                <Input
                  value={form.base_url}
                  onChange={(e) => setForm((s) => ({ ...s, base_url: e.target.value }))}
                  placeholder="https://api.example.com/v1"
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs">Max Turns</Label>
                <Input
                  type="number"
                  min={1}
                  max={90}
                  value={form.max_turns}
                  onChange={(e) => setForm((s) => ({ ...s, max_turns: Math.max(1, Math.min(90, Number(e.target.value) || 12)) }))}
                />
              </div>
            </div>
          </div>

          {testResult && (
            <div className={`rounded-lg border px-3 py-2 flex items-start gap-2 text-sm ${testResult.ok ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700" : "border-red-500/40 bg-red-500/10 text-red-700"}`}>
              {testResult.ok ? <CheckCircle2 className="h-4 w-4 mt-0.5 shrink-0" /> : <CircleAlert className="h-4 w-4 mt-0.5 shrink-0" />}
              <div className="flex-1 whitespace-pre-wrap break-words text-xs">
                {testResult.message}
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={test} disabled={testing || saving}>
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Bot className="h-4 w-4" />}
            {testing ? "测试中…" : "测试连接"}
          </Button>
          <Button onClick={save} disabled={saving || testing}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? "保存中…" : "保存配置"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
