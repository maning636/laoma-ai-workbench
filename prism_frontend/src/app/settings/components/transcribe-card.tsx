"use client"

import { useCallback, useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useToast } from "@/components/ui/use-toast"
import { API_ENDPOINTS } from "@/lib/env"
import { AudioLines, Loader2, Save, TestTube2 } from "lucide-react"

type WhisperConfigResponse = {
  data?: {
    provider?: string
    api_key?: string
    base_url?: string | null
    model_name?: string | null
    extra_config?: Record<string, unknown> | null
    is_active?: boolean
  } | null
  detail?: string
  message?: string
}

type WhisperFormState = {
  modelName: string
}

const SERVICE_TYPE = "whisper"
const DEFAULT_MODEL = "base"

const WHISPER_MODEL_HINTS = [
  "tiny / base / small / medium / large",
  "tiny.en / base.en / small.en / medium.en / large.en",
]

function maskApiKey(key: string): string {
  if (!key) return ""
  if (key.length <= 6) return "*".repeat(key.length)
  return `${key.slice(0, 2)}****${key.slice(-4)}`
}

export function TranscribeCard() {
  const { toast } = useToast()
  const [form, setForm] = useState<WhisperFormState>({ modelName: DEFAULT_MODEL })
  const [savedConfig, setSavedConfig] = useState<WhisperConfigResponse["data"] | null>(null)
  const [showKey, setShowKey] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)
  const [loading, setLoading] = useState({ hydrate: false, save: false, test: false })

  const setField = useCallback(<K extends keyof WhisperFormState>(key: K, value: WhisperFormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }, [])

  const hydrate = useCallback(async () => {
    setLoading((prev) => ({ ...prev, hydrate: true }))
    try {
      const response = await fetch(`${API_ENDPOINTS.aiModelConfigs}/${SERVICE_TYPE}`, {
        cache: "no-store",
      })
      const payload = (await response.json().catch(() => ({}))) as WhisperConfigResponse
      if (!response.ok) {
        throw new Error(payload?.detail || "读取配置失败")
      }
      const data = payload?.data ?? null
      setSavedConfig(data)
      setForm({ modelName: data?.model_name || DEFAULT_MODEL })
    } catch (error) {
      console.error("Failed to load whisper config:", error)
      // 静默失败：本地 whisper 首次使用尚未配置
      setSavedConfig(null)
      setForm({ modelName: DEFAULT_MODEL })
    } finally {
      setLoading((prev) => ({ ...prev, hydrate: false }))
    }
  }, [])

  useEffect(() => {
    void hydrate()
  }, [hydrate])

  const saveConfig = useCallback(async () => {
    const modelName = form.modelName.trim()
    if (!modelName) {
      toast({
        title: "模型名不能为空",
        description: "请填写本地 whisper 模型名（如 base / small.en）。",
        variant: "destructive",
      })
      return
    }
    setLoading((prev) => ({ ...prev, save: true }))
    try {
      const response = await fetch(API_ENDPOINTS.aiModelConfigs, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          service_type: SERVICE_TYPE,
          provider: "local",
          api_key: "",
          base_url: null,
          model_name: modelName,
          extra_config: { engine: "faster-whisper", source: "easel-asr" },
          is_active: true,
        }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) {
        throw new Error(payload?.detail || payload?.message || "保存失败")
      }
      await hydrate()
      toast({
        title: "转录配置已保存",
        description: `本地 whisper 模型名：${modelName}`,
      })
    } catch (error) {
      toast({
        title: "保存失败",
        description: error instanceof Error ? error.message : String(error),
        variant: "destructive",
      })
    } finally {
      setLoading((prev) => ({ ...prev, save: false }))
    }
  }, [form.modelName, hydrate, toast])

  const runTest = useCallback(async () => {
    setLoading((prev) => ({ ...prev, test: true }))
    setTestResult(null)
    const startedAt = performance.now()
    try {
      // 1) 先确认后端在跑（本地引擎是否可达）
      const healthRes = await fetch(`${API_ENDPOINTS.base}/api/v1/system/health-check`, {
        cache: "no-store",
      })
      const healthPayload = await healthRes.json().catch(() => ({}))
      if (!healthRes.ok) {
        throw new Error(healthPayload?.detail || "后端未响应")
      }

      // 2) 触发一次 model-configs 读，验证配置持久化路径可写可读
      const cfgRes = await fetch(`${API_ENDPOINTS.aiModelConfigs}/${SERVICE_TYPE}`, {
        cache: "no-store",
      })
      if (!cfgRes.ok) {
        throw new Error("转录配置读取失败（可先保存一次）")
      }

      const elapsed = Math.round(performance.now() - startedAt)
      setTestResult({
        ok: true,
        message: `握手耗时 ${elapsed}ms ✓（后端与转录配置均可达）`,
      })
      toast({
        title: "转录通道自检通过",
        description: `握手耗时 ${elapsed}ms`,
      })
    } catch (error) {
      const elapsed = Math.round(performance.now() - startedAt)
      const message = `握手耗时 ${elapsed}ms ✗（${error instanceof Error ? error.message : "自检失败"}）`
      setTestResult({ ok: false, message })
      toast({
        title: "转录通道自检失败",
        description: error instanceof Error ? error.message : String(error),
        variant: "destructive",
      })
    } finally {
      setLoading((prev) => ({ ...prev, test: false }))
    }
  }, [toast])

  const maskedKey = showKey && savedConfig?.api_key ? savedConfig.api_key : maskApiKey(savedConfig?.api_key ?? "")

  return (
    <Card className="border-border/70 bg-card">
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-foreground">
          <AudioLines className="h-5 w-5 text-foreground/70" />
          <span>语音转录 / Whisper</span>
          <span className="font-mono text-[11px] text-muted-foreground">transcribe</span>
          <Badge
            variant="outline"
            className={
              savedConfig
                ? "border-border/80 bg-popover text-foreground"
                : "border-border/70 bg-card text-muted-foreground"
            }
          >
            {savedConfig ? "已配置" : "未配置"}
          </Badge>
        </CardTitle>
        <CardDescription className="text-muted-foreground">
          走本地 Easel faster-whisper 引擎（asr.py），Base URL 与 API Key 均不使用；仅在此指定模型名。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="transcribe-base-url">Base URL</Label>
            <Input
              id="transcribe-base-url"
              disabled
              readOnly
              value=""
              placeholder="本地引擎（无需填写）"
              onChange={() => {}}
              className="border-border/70 bg-card/50 text-muted-foreground/60"
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="transcribe-model">模型名</Label>
            <Input
              id="transcribe-model"
              value={form.modelName}
              onChange={(event) => setField("modelName", event.target.value)}
              placeholder="base"
            />
          </div>
        </div>

        <div className="rounded-xl border border-border/70 bg-card/40 px-4 py-3 text-xs leading-5 text-muted-foreground">
          推荐模型：
          {WHISPER_MODEL_HINTS.map((hint, idx) => (
            <div key={idx} className={idx === 0 ? "" : "pl-4"}>
              · {hint}
            </div>
          ))}
          首次运行会自动下载模型到本地 .venv 目录，耗时较长；网络不通时请检查代理设置。
        </div>

        {maskedKey ? (
          <div className="rounded-xl border border-border/70 bg-card p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-xs text-muted-foreground">API Key</div>
              <div className="flex items-center gap-2">
                <code className="rounded bg-popover px-2 py-0.5 text-xs text-foreground/80">
                  {maskedKey}
                </code>
                <button
                  type="button"
                  onClick={() => setShowKey((prev) => !prev)}
                  className="text-[11px] text-muted-foreground hover:text-foreground"
                >
                  {showKey ? "隐藏" : "显示"}
                </button>
              </div>
            </div>
            {showKey && savedConfig?.api_key ? (
              <div className="mt-1 text-[11px] text-foreground/50">
                该通道使用本地引擎，Key 为空；此处仅显示当前保存值。
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="rounded-xl border border-dashed border-border/70 bg-card/20 px-4 py-3 text-xs leading-5 text-muted-foreground">
          当前保存值：
          <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-3">
            <div>
              <div className="text-[11px] uppercase tracking-[0.2em] text-foreground/40">提供商</div>
              <div className="mt-1 text-sm text-foreground/80">{savedConfig?.provider || "local"}</div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.2em] text-foreground/40">模型名</div>
              <div className="mt-1 break-all text-sm text-foreground/80">
                {savedConfig?.model_name || form.modelName || "未保存"}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-[0.2em] text-foreground/40">Base URL</div>
              <div className="mt-1 break-all text-sm text-foreground/80">本地引擎（未启用）</div>
            </div>
          </div>
        </div>

        {testResult ? (
          <div
            className={[
              "rounded-xl border px-4 py-3 text-sm leading-5",
              testResult.ok
                ? "border-border/70 bg-card text-foreground"
                : "border-border/70 bg-card text-foreground/70",
            ].join(" ")}
          >
            {testResult.message}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button
            onClick={() => void saveConfig()}
            disabled={loading.save}
            className="border-border/80 bg-popover text-foreground hover:bg-accent/50"
          >
            {loading.save ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
            保存配置
          </Button>
          <Button
            variant="secondary"
            onClick={() => void runTest()}
            disabled={loading.test}
            className="border-border/70 bg-card text-foreground hover:bg-accent/40"
          >
            {loading.test ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <TestTube2 className="mr-2 h-4 w-4" />
            )}
            运行自测
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
