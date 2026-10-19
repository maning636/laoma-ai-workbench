import * as React from "react"
import {
  ArrowRight,
  Film,
  Image as ImageIcon,
  NotebookPen,
  Palette,
} from "lucide-react"

import type { LucideIcon } from "lucide-react"

import { AgentPickerStep } from "@/components/wizard/agent-picker-step"

import type { WizardStepDefinition } from "./wizard"

export interface ScenarioStepDef extends WizardStepDefinition {}

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
  /** Wizard 步骤（骨架实现，后续模块接入真实业务） */
  steps: ScenarioStepDef[]
}

/** 步骤通用包装：标题 + 描述 + 说明卡 */
function StepPlaceholder({
  title,
  description,
  hints,
}: {
  title: string
  description?: string
  hints?: string[]
}) {
  return (
    <div className="rounded-xl border border-border/60 bg-background/40 p-4">
      <p className="text-sm font-semibold text-foreground">{title}</p>
      {description && (
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      )}
      {hints && hints.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
          {hints.map((h) => (
            <li key={h}>· {h}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/** 平台多选（骨架） */
function PlatformPicker({
  platforms,
}: {
  platforms: { id: string; label: string }[]
}) {
  const [checked, setChecked] = React.useState<Record<string, boolean>>({})
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {platforms.map((p) => {
        const on = !!checked[p.id]
        return (
          <button
            key={p.id}
            type="button"
            onClick={() =>
              setChecked((prev) => ({ ...prev, [p.id]: !prev[p.id] }))
            }
            className={
              "rounded-lg border px-3 py-2 text-xs transition-colors " +
              (on
                ? "border-primary/50 bg-primary/10 text-foreground"
                : "border-border/60 bg-background/40 text-muted-foreground hover:text-foreground")
            }
          >
            {p.label}
          </button>
        )
      })}
    </div>
  )
}

const PUBLISH_PLATFORMS = [
  { id: "douyin", label: "抖音" },
  { id: "kuaishou", label: "快手" },
  { id: "bilibili", label: "B 站" },
  { id: "xhs", label: "小红书" },
  { id: "channels", label: "视频号" },
  { id: "tiktok", label: "TikTok" },
]

const IMAGE_TYPES = [
  "主图",
  "场景图",
  "细节图",
  "白底图",
  "卖点图",
  "服饰穿戴图",
  "首屏主视觉",
  "核心卖点图",
  "使用场景图",
  "规格参数表",
]

/** 场景1：AI 写稿发布 */
export const AI_WRITING_SCENARIO: ScenarioDefinition = {
  id: "ai-writing",
  title: "AI 写稿发布",
  description: "选题 → AI 生成标题/标签/正文 → 一键发布到 8 大平台",
  icon: NotebookPen,
  statusLabel: "已上线",
  target: "/campaigns",
  steps: [
    {
      title: "选择目标平台",
      description: "勾选要发布的平台",
      render: () => <PlatformPicker platforms={PUBLISH_PLATFORMS} />,
    },
    {
      title: "选题",
      description: "输入选题关键词，或稍后接入 AI 生成",
      render: () => (
        <StepPlaceholder
          title="输入选题方向"
          description="例如：'职场效率工具推荐'"
          hints={[
            "手动输入选题（当前骨架）",
            "后续接入 AI 生成选题（待实现）",
          ]}
        />
      ),
    },
    {
      title: "AI 生成内容",
      description: "由云端 LLM 生成标题/标签/正文",
      render: () => (
        <StepPlaceholder
          title="生成标题 / 标签 / 正文"
          description="调用云端 LLM 服务（骨架占位，后续接入）"
          hints={[
            "标题候选 × N",
            "标签候选 × N",
            "正文草稿（可编辑）",
          ]}
        />
      ),
    },
    {
      title: "确认并发布",
      description: "审核内容后一键发布",
      render: () => (
        <StepPlaceholder
          title="确认发布"
          description="发布到所选平台（当前骨架，不实际调用 API）"
          hints={["选择账号矩阵", "选择发布时间", "发布到 8 大平台"]}
        />
      ),
    },
  ],
}

/** 场景2：AI 生图（M1 完成后接入） */
export const AI_IMAGE_SCENARIO: ScenarioDefinition = {
  id: "ai-image",
  title: "AI 生图",
  description: "上传原图 → 选择智能体 → 选择类型 → 生成 → 编辑发布",
  icon: ImageIcon,
  statusLabel: "已上线",
  target: "/fusion/image-studio",
  steps: [
    {
      title: "上传原图",
      render: () => (
        <StepPlaceholder
          title="上传原图"
          description="JPG / PNG / WebP，最多 7 张（M1 完成后接入）"
        />
      ),
    },
    {
      title: "智能体选择（可选）",
      description: "接入 M2 · Agent Studio 训练的风格智能体",
      render: () => <AgentPickerStep />,
    },
    {
      title: "选择图片类型",
      render: () => (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {IMAGE_TYPES.map((t) => (
            <div
              key={t}
              className="rounded-lg border border-border/60 bg-background/40 px-2 py-2 text-center text-xs text-muted-foreground"
            >
              {t}
            </div>
          ))}
        </div>
      ),
    },
    {
      title: "生成",
      render: () => (
        <StepPlaceholder
          title="生成图片"
          description="M1 完成后接入 gpt-image-1 / ComfyUI 等后端"
        />
      ),
    },
    {
      title: "编辑 / 发布",
      render: () => (
        <StepPlaceholder
          title="编辑或发布"
          description="跳转图片编辑器或发布中心"
        />
      ),
    },
  ],
}

/** 场景3：视频流水线（Easel） */
export const VIDEO_PIPELINE_SCENARIO: ScenarioDefinition = {
  id: "video-pipeline",
  title: "视频流水线",
  description: "选择素材 → 流水线配置 → 一键生成",
  icon: Film,
  statusLabel: "已上线",
  target: "/video-pipeline",
  steps: [
    {
      title: "选择素材",
      render: () => (
        <StepPlaceholder
          title="选择视频素材"
          description="从素材库 / Easel 收件箱选择"
        />
      ),
    },
    {
      title: "流水线配置",
      render: () => (
        <StepPlaceholder
          title="配置流水线"
          description="剪辑、字幕、封面、水印等步骤"
        />
      ),
    },
    {
      title: "生成",
      render: () => (
        <StepPlaceholder
          title="生成视频"
          description="Easel 流水线异步执行"
        />
      ),
    },
  ],
}

/** 场景4：图片编辑（M5 已完成，一步跳转） */
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
        <StepPlaceholder
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

/** 场景卡片网格 */
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
