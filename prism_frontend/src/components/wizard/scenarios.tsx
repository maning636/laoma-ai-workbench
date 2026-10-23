import * as React from "react"
import {
  ArrowRight,
  CheckCircle2,
  Clapperboard,
  Film,
  Image as ImageIcon,
  Loader2,
  NotebookPen,
  Palette,
  Send,
  Sparkles,
  UploadCloud,
  Wand2,
  X,
} from "lucide-react"

import type { LucideIcon } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import {
  IMAGE_TYPES,
  buildEditorUrl,
  isAcceptedImage,
  type ImageTypeId,
} from "@/lib/image-studio"

import { AgentPickerStep } from "@/components/wizard/agent-picker-step"

import type { WizardStepDefinition } from "./wizard"
import {
  clearSceneDraft,
  getSceneDraft,
  setSceneDraft,
  subscribeAgentChangeToDraft,
  type AiImageDraft,
  type AiWritingDraft,
  type VideoPipelineDraft,
} from "./wizard-state-cache"

// 原为 `interface ScenarioStepDef extends WizardStepDefinition {}`，
// 空接口等价于父类型本身，用 type 别名表达同一件事（ESLint no-empty-object-type）。
export type ScenarioStepDef = WizardStepDefinition

export interface ScenarioDefinition {
  id: string
  title: string
  description: string
  /** 场景图标（lucide） */
  icon: LucideIcon
  /** 状态标签，如 "已上线" / "骨架" / "即将接入" */
  statusLabel?: string
  /** 目标路径，用于场景卡片"去开始"按钮 */
  target: string
  /** Wizard 步骤（M4 · Steps Fill 已接入实际功能） */
  steps: ScenarioStepDef[]
}

// ──────────────────────────────────────────────────────────────
// 通用组件
// ──────────────────────────────────────────────────────────────

/** 步骤通用包装：标题 + 描述 + 说明卡 */
function StepShell({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children?: React.ReactNode
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border/60 bg-background/40 p-4">
        <p className="text-sm font-semibold text-foreground">{title}</p>
        {description && (
          <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        )}
      </div>
      {children}
    </div>
  )
}

/** 简易 checkbox 卡片：单选用 CheckboxPrimitive 太重，用 button 切换更符合向导场景 */
function ToggleCard({
  label,
  hint,
  checked,
  onToggle,
  disabled,
}: {
  label: string
  hint?: string
  checked: boolean
  onToggle: () => void
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onToggle}
      className={
        "flex items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs transition-colors disabled:cursor-not-allowed disabled:opacity-60 " +
        (checked
          ? "border-primary/50 bg-primary/10 text-foreground"
          : "border-border/60 bg-background/40 text-muted-foreground hover:text-foreground")
      }
    >
      <span className="flex items-center gap-1.5">
        <span
          className={
            "flex h-3.5 w-3.5 items-center justify-center rounded-sm border " +
            (checked ? "border-primary bg-primary text-background" : "border-border/80 bg-background/60")
          }
        >
          {checked && <CheckCircle2 className="h-3 w-3" />}
        </span>
        <span className="font-medium">{label}</span>
      </span>
      {hint && <span className="text-[10px] text-muted-foreground">{hint}</span>}
    </button>
  )
}

/** 文件选择器（本地预览，dataURL） */
function FilePicker({
  accept,
  onFiles,
  files,
  allowMultiple,
  showPreview,
}: {
  accept: string
  onFiles: (files: File[]) => void
  files: File[]
  allowMultiple?: boolean
  showPreview?: boolean
}) {
  const inputRef = React.useRef<HTMLInputElement>(null)
  return (
    <div className="space-y-2">
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={allowMultiple}
        className="hidden"
        onChange={(e) => {
          const list = Array.from(e.target.files ?? [])
          onFiles(list)
          // 允许重复选同一文件：清空 value
          e.target.value = ""
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => inputRef.current?.click()}
        >
          <UploadCloud className="h-3.5 w-3.5" />
          选择文件
        </Button>
        <span className="text-xs text-muted-foreground">
          已选 {files.length} 个文件
        </span>
      </div>
      {files.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {files.map((f, idx) => (
            <div
              key={idx}
              className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-background/40 px-3 py-2 text-xs"
            >
              <span className="truncate text-foreground">{f.name}</span>
              <span className="shrink-0 text-[10px] text-muted-foreground">
                {(f.size / 1024).toFixed(1)} KB
              </span>
            </div>
          ))}
        </div>
      )}
      {showPreview && files.length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {files.slice(0, 6).map((f, idx) => (
            <img
              key={idx}
              src={filePreviewCache.get(f.name + f.size + f.lastModified) ?? ""}
              alt={f.name}
              className="h-20 w-full rounded-lg border border-border/60 object-cover"
            />
          ))}
        </div>
      )}
    </div>
  )
}

/** 图片预览缓存：因为 File 对象不可序列化，用 name+size+mtime 作 key 存 dataURL */
const filePreviewCache = new Map<string, string>()

async function loadImagePreviews(files: File[]) {
  for (const f of files) {
    const key = f.name + f.size + f.lastModified
    if (filePreviewCache.has(key)) continue
    if (f.type.startsWith("image/")) {
      try {
        const reader = new FileReader()
        const dataUrl = await new Promise<string>((resolve) => {
          reader.onload = () => resolve(String(reader.result))
          reader.onerror = () => resolve("")
          reader.readAsDataURL(f)
        })
        if (dataUrl) filePreviewCache.set(key, dataUrl)
      } catch {
        // ignore
      }
    }
  }
}

// ──────────────────────────────────────────────────────────────
// 场景1 · AI 写稿发布
// ──────────────────────────────────────────────────────────────

export interface PublishPlatform {
  id: string
  label: string
  /**
   * 后端是否已有真实发布通道（发布工具 + 登录适配器齐备）。
   * false = 仅供文案风格参考，向导中禁选，避免走到发布会失败。
   * 与后端对齐（fastapi publish_tools + platforms 登录适配器）：
   *   douyin / kuaishou / bilibili / xhs / channels 为 true
   */
  publishable: boolean
}

export const PUBLISH_PLATFORMS: PublishPlatform[] = [
  { id: "douyin", label: "抖音", publishable: true },
  { id: "kuaishou", label: "快手", publishable: true },
  { id: "bilibili", label: "B 站", publishable: true },
  { id: "xhs", label: "小红书", publishable: true },
  { id: "channels", label: "视频号", publishable: true },
  { id: "zhihu", label: "知乎", publishable: false },
  { id: "toutiao", label: "头条", publishable: false },
  { id: "xigua", label: "西瓜", publishable: false },
]

const AI_WRITING_SCENE_ID = "ai-writing"

const INITIAL_AI_WRITING_DRAFT: () => AiWritingDraft = () => ({
  platformIds: [],
  topic: "",
  titleCandidates: [],
  title: "",
  tags: [],
  body: "",
  published: false,
  publishedAt: 0,
})

function loadAiWritingDraft(): AiWritingDraft {
  return getSceneDraft(AI_WRITING_SCENE_ID, INITIAL_AI_WRITING_DRAFT)
}
function saveAiWritingDraft(patch: Partial<AiWritingDraft>) {
  // 合并到 cache 里的最新 draft，避免同一 step 内多次 save 用陈旧 snapshot 覆盖其他字段
  setSceneDraft(AI_WRITING_SCENE_ID, { ...loadAiWritingDraft(), ...patch })
}

function AiWritingPlatformStep() {
  const draft = React.useMemo(loadAiWritingDraft, [])
  const [selected, setSelected] = React.useState<string[]>(draft.platformIds)
  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
      // 各步骤只 patch 自己负责的字段，其余字段沿用 mount 时快照
      saveAiWritingDraft({ ...draft, platformIds: next })
      return next
    })
  }
  return (
    <StepShell
      title="选择目标平台"
      description="勾选要发布的平台（可多选）"
    >
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {PUBLISH_PLATFORMS.map((p) => (
          <ToggleCard
            key={p.id}
            label={p.label}
            hint={p.publishable ? p.id : "暂不支持发布（仅文案风格）"}
            checked={selected.includes(p.id)}
            onToggle={() => toggle(p.id)}
            disabled={!p.publishable}
          />
        ))}
      </div>
    </StepShell>
  )
}

/** Mock AI 选题：根据 prompt 关键词返回几个候选 */
export function mockAiSuggestTopics(topicHint: string): string[] {
  const hint = topicHint.trim()
  const base = hint || "内容创作"
  return [
    `${base}：给创作者的 3 个进阶技巧`,
    `2026 年 ${base} 趋势：值得关注的新方向`,
    `如何用 AI 提升 ${base} 的产出效率`,
  ]
}

function AiWritingTopicStep() {
  const draft = React.useMemo(loadAiWritingDraft, [])
  const [topic, setTopic] = React.useState(draft.topic)
  const [suggestions, setSuggestions] = React.useState<string[]>([])
  const [generating, setGenerating] = React.useState(false)

  const handleGenerate = () => {
    setGenerating(true)
    setTimeout(() => {
      const s = mockAiSuggestTopics(topic)
      setSuggestions(s)
      setGenerating(false)
    }, 400)
  }
  const handlePick = (s: string) => {
    setTopic(s)
    saveAiWritingDraft({ ...draft, topic: s })
  }

  return (
    <StepShell
      title="选题"
      description="输入你的选题方向；也可以让 AI 基于关键词生成候选"
    >
      <div className="space-y-2">
        <Textarea
          value={topic}
          placeholder="例如：职场效率工具推荐"
          onChange={(e) => {
            setTopic(e.target.value)
            saveAiWritingDraft({ ...draft, topic: e.target.value })
          }}
        />
        <div className="flex items-center justify-between">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={generating}
            onClick={handleGenerate}
          >
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            {generating ? "生成中…" : "AI 生成选题"}
          </Button>
          <span className="text-[10px] text-muted-foreground">
            选中平台：{draft.platformIds.length > 0 ? draft.platformIds.join("、") : "（未选）"}
          </span>
        </div>
      </div>
      {suggestions.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-foreground">AI 建议：</p>
          {suggestions.map((s, i) => (
            <button
              key={i}
              type="button"
              onClick={() => handlePick(s)}
              className="block w-full rounded-lg border border-border/60 bg-background/40 px-3 py-2 text-left text-xs text-foreground hover:border-primary/40"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </StepShell>
  )
}

/** Mock AI 生成：基于选题生成标题候选、标签、正文 */
export function mockAiGenerateContent(topic: string) {
  const t = topic.trim() || "新内容"
  return {
    titleCandidates: [
      `${t}：3 分钟看懂全流程`,
      `一文读懂 ${t} 的关键要点`,
      `别再错过！${t} 的 5 个技巧`,
    ],
    tags: ["自媒体", "AI", "效率", "内容创作", t.slice(0, 6)],
    body: `今天分享一个关于「${t}」的思考。\n\n作为创作者，我们都希望把内容做得更有价值。这里给出几个方向：\n1. 从用户痛点出发，明确内容目标；\n2. 用 AI 工具放大产能，但不要替代思考；\n3. 数据驱动，根据平台反馈快速迭代。\n\n更多细节见评论区，欢迎交流。`,
  }
}

function AiWritingGenerateStep() {
  const draft = React.useMemo(loadAiWritingDraft, [])
  const [generating, setGenerating] = React.useState(false)
  const [result, setResult] = React.useState<{
    titleCandidates: string[]
    tags: string[]
    body: string
  } | null>(() =>
    draft.titleCandidates.length > 0
      ? {
          titleCandidates: draft.titleCandidates,
          tags: draft.tags,
          body: draft.body,
        }
      : null,
  )
  const [title, setTitle] = React.useState(draft.title)
  const [body, setBody] = React.useState(draft.body)

  const handleGenerate = () => {
    setGenerating(true)
    setTimeout(() => {
      const r = mockAiGenerateContent(draft.topic)
      setResult(r)
      setTitle(r.titleCandidates[0])
      setBody(r.body)
      saveAiWritingDraft({
        ...draft,
        titleCandidates: r.titleCandidates,
        tags: r.tags,
        body: r.body,
        title: r.titleCandidates[0],
      })
      setGenerating(false)
    }, 800)
  }

  return (
    <StepShell
      title="AI 生成标题 / 标签 / 正文"
      description={`基于选题「${draft.topic || "（未填写）"}」调用云端 LLM（Mock）`}
    >
      <div className="space-y-3">
        {!result && (
          <Button type="button" size="sm" disabled={generating} onClick={handleGenerate}>
            {generating ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Wand2 className="h-3.5 w-3.5" />
            )}
            {generating ? "生成中…" : "开始生成"}
          </Button>
        )}
        {generating && !result && (
          <div className="rounded-lg border border-border/60 bg-background/40 p-3 text-xs text-muted-foreground">
            正在调用云端 LLM，请稍候…
          </div>
        )}
        {result && (
          <>
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-foreground">标题候选</p>
              <div className="space-y-1">
                {result.titleCandidates.map((t, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      setTitle(t)
                      saveAiWritingDraft({ ...draft, title: t })
                    }}
                    className={
                      "block w-full rounded-lg border px-3 py-1.5 text-left text-xs transition-colors " +
                      (title === t
                        ? "border-primary/50 bg-primary/10 text-foreground"
                        : "border-border/60 bg-background/40 text-muted-foreground hover:text-foreground")
                    }
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-foreground">标签</p>
              <div className="flex flex-wrap gap-1">
                {result.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-border/60 bg-background/40 px-2 py-0.5 text-[10px] text-muted-foreground"
                  >
                    #{tag}
                  </span>
                ))}
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-xs font-medium text-foreground">正文（可编辑）</p>
              <Textarea
                value={body}
                onChange={(e) => {
                  setBody(e.target.value)
                  saveAiWritingDraft({ ...draft, body: e.target.value })
                }}
              />
            </div>
          </>
        )}
      </div>
    </StepShell>
  )
}

function AiWritingPublishStep() {
  const draft = React.useMemo(loadAiWritingDraft, [])
  const [publishing, setPublishing] = React.useState(false)

  const handlePublish = () => {
    setPublishing(true)
    setTimeout(() => {
      saveAiWritingDraft({
        ...draft,
        published: true,
        publishedAt: Date.now(),
      })
      setPublishing(false)
    }, 700)
  }

  return (
    <StepShell
      title="确认并发布"
      description="预览内容并发送到所选平台（Mock，不真实调用 API）"
    >
      <div className="space-y-3">
        <div className="rounded-lg border border-border/60 bg-background/40 p-3 space-y-2">
          <p className="text-xs font-medium text-foreground">标题</p>
          <p className="text-sm font-semibold text-foreground">
            {draft.title || "（未生成标题）"}
          </p>
          <div className="flex flex-wrap gap-1">
            {draft.tags.map((t) => (
              <span
                key={t}
                className="rounded-full border border-border/60 bg-background/40 px-2 py-0.5 text-[10px] text-muted-foreground"
              >
                #{t}
              </span>
            ))}
          </div>
          <p className="text-xs font-medium text-foreground">正文</p>
          <pre className="whitespace-pre-wrap text-xs text-foreground/90">
            {draft.body || "（未生成正文）"}
          </pre>
        </div>
        <div className="rounded-lg border border-border/60 bg-background/40 p-3 space-y-1">
          <p className="text-xs font-medium text-foreground">目标平台</p>
          <p className="text-xs text-muted-foreground">
            {draft.platformIds.length > 0
              ? draft.platformIds
                  .map((id) => PUBLISH_PLATFORMS.find((p) => p.id === id)?.label ?? id)
                  .join("、")
              : "（未选平台）"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            disabled={publishing || draft.published}
            onClick={handlePublish}
          >
            {publishing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : draft.published ? (
              <CheckCircle2 className="h-3.5 w-3.5" />
            ) : (
              <Send className="h-3.5 w-3.5" />
            )}
            {publishing ? "发布中…" : draft.published ? "已发布" : "确认发布"}
          </Button>
          {draft.published && (
            <span className="text-xs text-emerald-600 dark:text-emerald-400">
              Mock 发布成功 · 已发送到 {draft.platformIds.length} 个平台
            </span>
          )}
        </div>
      </div>
    </StepShell>
  )
}

export const AI_WRITING_SCENARIO: ScenarioDefinition = {
  id: AI_WRITING_SCENE_ID,
  title: "AI 写稿发布",
  description: "选题 → AI 生成标题/标签/正文 → 一键发布到 8 大平台（当前为演示流程，未接真实 LLM 与发布 API）",
  icon: NotebookPen,
  statusLabel: "演示流程",
  target: "/campaigns",
  steps: [
    { title: "选择目标平台", description: "勾选要发布的平台", render: () => <AiWritingPlatformStep /> },
    { title: "选题", description: "输入选题或让 AI 生成候选", render: () => <AiWritingTopicStep /> },
    { title: "AI 生成内容", description: "生成标题 / 标签 / 正文", render: () => <AiWritingGenerateStep /> },
    { title: "确认并发布", description: "预览内容并发送到平台", render: () => <AiWritingPublishStep /> },
  ],
}

// ──────────────────────────────────────────────────────────────
// 场景2 · AI 生图（5 步）
// ──────────────────────────────────────────────────────────────

const AI_IMAGE_SCENE_ID = "ai-image"

const INITIAL_AI_IMAGE_DRAFT: () => AiImageDraft = () => ({
  referencePreview: [],
  agentId: "",
  imageTypeId: "",
  generatedUrls: [],
  generatedTaskId: "",
})

function loadAiImageDraft(): AiImageDraft {
  return getSceneDraft(AI_IMAGE_SCENE_ID, INITIAL_AI_IMAGE_DRAFT)
}
function saveAiImageDraft(patch: Partial<AiImageDraft>) {
  setSceneDraft(AI_IMAGE_SCENE_ID, { ...loadAiImageDraft(), ...patch })
}

function AiImageUploadStep() {
  const draft = React.useMemo(loadAiImageDraft, [])
  const [files, setFiles] = React.useState<File[]>([])

  const handleFiles = async (picked: File[]) => {
    const accepted = picked.filter(isAcceptedImage).slice(0, 7)
    setFiles(accepted)
    await loadImagePreviews(accepted)
    const previews = accepted.map((f) => ({
      fileName: f.name,
      dataUrl: filePreviewCache.get(f.name + f.size + f.lastModified) ?? "",
    }))
    saveAiImageDraft({ ...draft, referencePreview: previews })
  }

  const handleRemove = (idx: number) => {
    const nextFiles = files.filter((_, i) => i !== idx)
    setFiles(nextFiles)
    const previews = nextFiles.map((f) => ({
      fileName: f.name,
      dataUrl: filePreviewCache.get(f.name + f.size + f.lastModified) ?? "",
    }))
    saveAiImageDraft({ ...draft, referencePreview: previews })
  }

  return (
    <StepShell
      title="上传原图"
      description="JPG / PNG / WebP，最多 7 张（本地预览，不真的上传到后端）"
    >
      <div className="space-y-3">
        <FilePicker
          accept="image/png,image/jpeg,image/webp"
          allowMultiple
          onFiles={handleFiles}
          files={files}
          showPreview
        />
        <div className="flex justify-end gap-2">
          {files.length > 0 && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setFiles([])
                saveAiImageDraft({ ...draft, referencePreview: [] })
              }}
            >
              <X className="h-3.5 w-3.5" />
              清空
            </Button>
          )}
          <span className="self-center text-[10px] text-muted-foreground">
            下一步会带上 {files.length} 张参考图
          </span>
        </div>
      </div>
    </StepShell>
  )
}

function AiImageAgentStep() {
  // 挂载时确保 agent 变更订阅已绑定
  React.useEffect(() => {
    subscribeAgentChangeToDraft()
  }, [])
  return <AgentPickerStep />
}

function AiImageTypeStep() {
  const draft = React.useMemo(loadAiImageDraft, [])
  const [selectedId, setSelectedId] = React.useState<ImageTypeId | "none">(
    (draft.imageTypeId as ImageTypeId | "none") || "none",
  )
  const handlePick = (id: ImageTypeId | "none") => {
    setSelectedId(id)
    saveAiImageDraft({
      ...draft,
      imageTypeId: id === "none" ? "" : id,
    })
  }
  return (
    <StepShell
      title="选择图片类型"
      description="选择后将自动作为 prompt 前缀注入到生成请求"
    >
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {IMAGE_TYPES.map((t) => (
          <ToggleCard
            key={t.id}
            label={t.label}
            hint={t.description}
            checked={selectedId === t.id}
            onToggle={() => handlePick(selectedId === t.id ? "none" : t.id)}
          />
        ))}
      </div>
      {selectedId !== "none" && (
        <div className="rounded-lg border border-primary/40 bg-primary/5 p-3 text-xs text-primary">
          已选择：{IMAGE_TYPES.find((t) => t.id === selectedId)?.label}
          {draft.agentId && " · 已选智能体，将注入 style_prompt"}
        </div>
      )}
    </StepShell>
  )
}

/** Mock 生成：直接返回 picsum 图片 URL */
export function mockAiGenerateImages(seed: string, count = 4): string[] {
  const s = encodeURIComponent(seed.trim() || "prism")
  return Array.from({ length: count }, (_, i) =>
    `https://picsum.photos/seed/${s}-${i + 1}/512/512.jpg`,
  )
}

function AiImageGenerateStep() {
  const draft = React.useMemo(loadAiImageDraft, [])
  const [generating, setGenerating] = React.useState(false)
  const [urls, setUrls] = React.useState<string[]>(draft.generatedUrls)
  const [taskId, setTaskId] = React.useState(draft.generatedTaskId)

  const handleGenerate = () => {
    setGenerating(true)
    const topic = `${draft.imageTypeId || "cover"}-${draft.agentId || "default"}`
    const id = `gen_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    setTaskId(id)
    setTimeout(() => {
      const result = mockAiGenerateImages(topic, 4)
      setUrls(result)
      saveAiImageDraft({
        ...draft,
        generatedUrls: result,
        generatedTaskId: id,
      })
      setGenerating(false)
    }, 900)
  }

  return (
    <StepShell
      title="生成图片"
      description="调用 /api/v1/ai-design/generate（Mock，使用本地种子返回 picsum 图片）"
    >
      <div className="space-y-3">
        {!generating && urls.length === 0 && (
          <Button type="button" size="sm" onClick={handleGenerate}>
            <Wand2 className="h-3.5 w-3.5" />
            开始生成（4 张）
          </Button>
        )}
        {generating && (
          <div className="rounded-lg border border-border/60 bg-background/40 p-4 flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在调用后端生成任务 {taskId.slice(0, 14)}…
          </div>
        )}
        {urls.length > 0 && (
          <div className="grid grid-cols-2 gap-2">
            {urls.map((u, i) => (
              <div
                key={i}
                className="rounded-lg border border-border/60 bg-background/40 p-2 space-y-1"
              >
                <img
                  src={u}
                  alt={`生成结果 ${i + 1}`}
                  className="aspect-square w-full rounded-md object-cover"
                />
                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                  <span>#{i + 1}</span>
                  <button
                    type="button"
                    className="text-primary hover:underline"
                    onClick={() => {
                      window.open(buildEditorUrl(u), "_blank", "noopener,noreferrer")
                    }}
                  >
                    编辑
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </StepShell>
  )
}

function AiImageResultStep() {
  const draft = React.useMemo(loadAiImageDraft, [])
  const urls = draft.generatedUrls
  if (urls.length === 0) {
    return (
      <StepShell
        title="生成结果"
        description="尚未生成任何图片，请回到上一步执行生成"
      />
    )
  }
  return (
    <StepShell
      title="生成结果"
      description={`${urls.length} 张图片已就绪，点击"编辑"进入 M5 图片编辑器`}
    >
      <div className="grid grid-cols-2 gap-2">
        {urls.map((u, i) => (
          <div
            key={i}
            className="rounded-lg border border-border/60 bg-background/40 p-2 space-y-1"
          >
            <img
              src={u}
              alt={`结果 ${i + 1}`}
              className="aspect-square w-full rounded-md object-cover"
            />
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-muted-foreground">#{i + 1}</span>
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="h-7 text-xs"
                onClick={() => {
                  window.open(buildEditorUrl(u), "_blank", "noopener,noreferrer")
                }}
              >
                <Clapperboard className="h-3 w-3" />
                编辑
              </Button>
            </div>
          </div>
        ))}
      </div>
    </StepShell>
  )
}

export const AI_IMAGE_SCENARIO: ScenarioDefinition = {
  id: AI_IMAGE_SCENE_ID,
  title: "AI 生图",
  description: "上传原图 → 选择智能体 → 选择类型 → 生成 → 编辑发布（当前为演示流程，使用占位图，未接真实生图 API）",
  icon: ImageIcon,
  statusLabel: "演示流程",
  target: "/fusion/image-studio",
  steps: [
    { title: "上传原图", render: () => <AiImageUploadStep /> },
    { title: "智能体选择（可选）", description: "接入 M2 · Agent Studio 训练的风格智能体", render: () => <AiImageAgentStep /> },
    { title: "选择图片类型", render: () => <AiImageTypeStep /> },
    { title: "生成", render: () => <AiImageGenerateStep /> },
    { title: "编辑 / 发布", render: () => <AiImageResultStep /> },
  ],
}

// ──────────────────────────────────────────────────────────────
// 场景3 · 视频流水线（Easel）
// ──────────────────────────────────────────────────────────────

const VIDEO_PIPELINE_SCENE_ID = "video-pipeline"

const INITIAL_VIDEO_PIPELINE_DRAFT: () => VideoPipelineDraft = () => ({
  materials: [],
  config: {
    addSubtitle: true,
    addCover: true,
    addWatermark: false,
    trimSilent: true,
    autoBgm: false,
  },
  taskId: "",
})

function loadVideoPipelineDraft(): VideoPipelineDraft {
  return getSceneDraft(VIDEO_PIPELINE_SCENE_ID, INITIAL_VIDEO_PIPELINE_DRAFT)
}
function saveVideoPipelineDraft(draft: VideoPipelineDraft) {
  setSceneDraft(VIDEO_PIPELINE_SCENE_ID, draft)
}

function VideoPipelineMaterialStep() {
  const draft = React.useMemo(loadVideoPipelineDraft, [])
  const [files, setFiles] = React.useState<File[]>([])

  return (
    <StepShell
      title="选择视频素材"
      description="从本地选择视频文件（Mock：不做真实上传）"
    >
      <div className="space-y-2">
        <FilePicker
          accept="video/mp4,video/quicktime,video/webm"
          allowMultiple
          onFiles={(picked) => {
            setFiles(picked)
            saveVideoPipelineDraft({
              ...draft,
              materials: picked.map((f) => ({ fileName: f.name, size: f.size })),
            })
          }}
          files={files}
        />
        {files.length > 0 && (
          <div className="flex justify-end">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setFiles([])
                saveVideoPipelineDraft({ ...draft, materials: [] })
              }}
            >
              <X className="h-3.5 w-3.5" />
              清空
            </Button>
          </div>
        )}
      </div>
    </StepShell>
  )
}

function VideoPipelineConfigStep() {
  const draft = React.useMemo(loadVideoPipelineDraft, [])
  const toggle = (key: keyof VideoPipelineDraft["config"]) => {
    const next = {
      ...draft,
      config: { ...draft.config, [key]: !draft.config[key] },
    }
    saveVideoPipelineDraft(next)
  }
  return (
    <StepShell
      title="流水线配置"
      description="Easel 剪辑步骤（Mock，实际由后端 Easel 执行）"
    >
      <div className="grid grid-cols-2 gap-2">
        <ToggleCard
          label="添加字幕"
          hint="自动识别语音"
          checked={draft.config.addSubtitle}
          onToggle={() => toggle("addSubtitle")}
        />
        <ToggleCard
          label="生成封面"
          hint="AI 挑选关键帧"
          checked={draft.config.addCover}
          onToggle={() => toggle("addCover")}
        />
        <ToggleCard
          label="添加水印"
          hint="品牌角标"
          checked={draft.config.addWatermark}
          onToggle={() => toggle("addWatermark")}
        />
        <ToggleCard
          label="去除静音"
          hint="自动剪除空白"
          checked={draft.config.trimSilent}
          onToggle={() => toggle("trimSilent")}
        />
        <ToggleCard
          label="自动配乐"
          hint="按节奏选 BGM"
          checked={draft.config.autoBgm}
          onToggle={() => toggle("autoBgm")}
        />
      </div>
      <div className="rounded-lg border border-border/60 bg-background/40 p-3 text-xs text-muted-foreground">
        已选素材 {draft.materials.length} 个 · 流水线将异步执行 Easel job
      </div>
    </StepShell>
  )
}

function VideoPipelineGenerateStep() {
  const draft = React.useMemo(loadVideoPipelineDraft, [])
  const [generating, setGenerating] = React.useState(false)
  const [taskId, setTaskId] = React.useState(draft.taskId)
  const [done, setDone] = React.useState(Boolean(draft.taskId))

  const handleGenerate = () => {
    setGenerating(true)
    const id = `pipeline_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
    setTaskId(id)
    setTimeout(() => {
      saveVideoPipelineDraft({ ...draft, taskId: id })
      setGenerating(false)
      setDone(true)
    }, 1200)
  }

  return (
    <StepShell
      title="生成视频"
      description="Easel 流水线异步执行（Mock 完成时间 1.2s）"
    >
      <div className="space-y-3">
        {!generating && !done && (
          <Button type="button" size="sm" onClick={handleGenerate}>
            <Film className="h-3.5 w-3.5" />
            开始生成
          </Button>
        )}
        {generating && (
          <div className="rounded-lg border border-border/60 bg-background/40 p-4 flex items-center gap-2 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Easel 流水线正在执行 {taskId.slice(0, 20)}…
          </div>
        )}
        {done && (
          <div className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-3 space-y-1">
            <p className="text-xs font-medium text-emerald-600 dark:text-emerald-400">
              Mock 生成完成
            </p>
            <p className="text-xs text-muted-foreground">Task ID: {taskId}</p>
            <p className="text-xs text-muted-foreground">
              实际部署后会接入 /video-pipeline 页面查看真实进度
            </p>
          </div>
        )}
      </div>
    </StepShell>
  )
}

export const VIDEO_PIPELINE_SCENARIO: ScenarioDefinition = {
  id: VIDEO_PIPELINE_SCENE_ID,
  title: "视频流水线",
  description: "选择素材 → 流水线配置 → 一键生成（当前为演示流程，未接真实上传与渲染）",
  icon: Film,
  statusLabel: "演示流程",
  target: "/video-pipeline",
  steps: [
    { title: "选择素材", render: () => <VideoPipelineMaterialStep /> },
    { title: "流水线配置", render: () => <VideoPipelineConfigStep /> },
    { title: "生成", render: () => <VideoPipelineGenerateStep /> },
  ],
}

// ──────────────────────────────────────────────────────────────
// 场景4 · 图片编辑（M5 已完成，一步跳转）
// ──────────────────────────────────────────────────────────────

export const IMAGE_EDITOR_SCENARIO: ScenarioDefinition = {
  id: "image-editor",
  title: "图片编辑",
  description: "在线图片编辑器（M5 已完成）",
  icon: Palette,
  statusLabel: "已上线",
  target: "/tools/image-editor",
  steps: [
    {
      title: "进入编辑器",
      render: () => (
        <StepShell
          title="即将跳转到图片编辑器"
          description="点击下一步将打开 /tools/image-editor"
        />
      ),
    },
  ],
}

export const ALL_SCENARIOS: ScenarioDefinition[] = [
  AI_WRITING_SCENARIO,
  AI_IMAGE_SCENARIO,
  VIDEO_PIPELINE_SCENARIO,
  IMAGE_EDITOR_SCENARIO,
]

export function getScenarioById(id: string): ScenarioDefinition | undefined {
  return ALL_SCENARIOS.find((s) => s.id === id)
}

/** Wizard RESET 时清理该场景的跨步骤 draft */
export function resetScenarioDraft(id: string): void {
  clearSceneDraft(id)
}

// ──────────────────────────────────────────────────────────────
// 场景卡片网格
// ──────────────────────────────────────────────────────────────

export function ScenarioGrid({
  onStart,
  className,
}: {
  onStart: (scenario: ScenarioDefinition) => void
  className?: string
}) {
  return (
    <div className={"grid gap-4 md:grid-cols-2 lg:grid-cols-4 " + (className ?? "")}>
      {ALL_SCENARIOS.map((scenario) => {
        const Icon = scenario.icon
        return (
          <ScenarioCard key={scenario.id} scenario={scenario} onStart={onStart} Icon={Icon} />
        )
      })}
    </div>
  )
}

export function ScenarioCard({
  scenario,
  onStart,
  Icon,
}: {
  scenario: ScenarioDefinition
  onStart: (scenario: ScenarioDefinition) => void
  Icon: LucideIcon
}) {
  return (
    <div className="group relative overflow-hidden rounded-2xl border border-border/60 bg-card/70 p-[1px] transition-colors hover:border-primary/40">
      <div className="flex h-full flex-col rounded-2xl bg-background/40 p-4 transition group-hover:bg-card">
        <div className="flex items-start justify-between">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-border/60 bg-accent/50 text-foreground">
            <Icon className="h-5 w-5" />
          </div>
          {scenario.statusLabel && (
            <span className="rounded-full border border-border/60 bg-accent/50 px-2 py-0.5 text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
              {scenario.statusLabel}
            </span>
          )}
        </div>
        <div className="mt-3 space-y-1">
          <p className="text-base font-semibold text-foreground">{scenario.title}</p>
          <p className="text-xs text-muted-foreground">{scenario.description}</p>
        </div>
        <div className="mt-4 flex items-center justify-between">
          <span className="text-[10px] uppercase tracking-[0.08em] text-muted-foreground">
            {scenario.steps.length} 步
          </span>
          <button
            type="button"
            onClick={() => onStart(scenario)}
            className="inline-flex items-center gap-1 rounded-lg border border-primary/40 bg-primary/10 px-2.5 py-1.5 text-xs font-medium text-primary transition hover:bg-primary hover:text-foreground"
          >
            去开始
            <ArrowRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
