"use client"

import * as React from "react"
import { useRouter, useSearchParams } from "next/navigation"

import { Check, ChevronLeft, ChevronRight } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import { cn } from "@/lib/utils"

import {
  type WizardState,
  type WizardAction,
  wizardReducer,
  canNext,
  canPrev,
  isLastStep,
} from "./wizard-core"
import { buildWizardQuery, parseWizardQuery } from "./url-sync"

export type { WizardState, WizardAction }

export interface WizardStepProps {
  state: WizardState
  dispatch: React.Dispatch<WizardAction>
  index: number
}

export interface WizardStepDefinition {
  title: string
  description?: string
  /** 步骤内容渲染。返回 null 表示由上层决定默认视图 */
  render: (ctx: WizardStepProps) => React.ReactNode
}

export interface WizardProps {
  /** 场景 id（如 "ai-writing"）。传入后组件接管该场景的 Wizard */
  scene: string
  title?: string
  description?: string
  steps: WizardStepDefinition[]
  /** 完成后的操作：跳走或显示空态 */
  onComplete?: (state: WizardState) => void
  /** 完成页展示"完成"信息时的自定义操作区 */
  doneActions?: React.ReactNode
  className?: string
}

/**
 * 通用 Wizard。
 *
 * - 使用 useReducer 管理状态；
 * - 与 URL query (?scene=xxx&step=N) 双向同步（scene 存在时）；
 * - 每一步通过 render(ctx) 动态渲染内容；
 * - 空 steps 时不渲染（防御性）。
 */
export function Wizard({
  scene,
  title,
  description,
  steps,
  onComplete,
  doneActions,
  className,
}: WizardProps) {
  const searchParams = useSearchParams()
  const router = useRouter()
  const total = steps.length

  // 从 URL 计算初始 step（仅当 ?scene 匹配时）
  const [initialState] = React.useState<WizardState>(() => {
    const parsed = parseWizardQuery(searchParams, total)
    // 仅当 URL 的 scene 与本组件的 scene 一致时才采用解析结果
    if (parsed.scene !== scene) {
      return {
        scene: null,
        step: 0,
        total,
        status: total === 0 ? "idle" : "stepping",
      }
    }
    return {
      scene,
      step: parsed.step,
      total,
      status: parsed.status,
    }
  })

  const [state, dispatch] = React.useReducer(wizardReducer, initialState)

  // state → URL 同步（用户操作后追加/更新 query）
  React.useEffect(() => {
    if (state.scene !== scene) return
    const sp = buildWizardQuery(searchParams, {
      step: state.step,
      done: state.status === "done",
    })
    if (sp.toString() !== searchParams.toString()) {
      router.replace(`?${sp.toString()}`, { scroll: false })
    }
  }, [state.step, state.status, state.scene, scene, searchParams, router])

  // 进入 done 时触发 onComplete（用于外部跳转）
  React.useEffect(() => {
    if (state.status === "done" && state.scene === scene) {
      onComplete?.(state)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.status])

  const step = steps[state.step]
  const showDone = state.status === "done"

  const handleNext = () => {
    if (isLastStep(state)) {
      // 进入"已完成"视图；真正的跳转由 doneActions 里的按钮触发
      dispatch({ type: "DONE" })
    } else {
      dispatch({ type: "NEXT" })
    }
  }

  const handleReset = () => {
    // 清空 URL 中的 scene/step/done，回到干净状态；
    // 由于 URL scene 移除会卸载本组件，reducer 状态不再需要清理。
    const sp = buildWizardQuery(searchParams, { scene: "", step: null, done: null })
    const qs = sp.toString()
    router.replace(qs ? `?${qs}` : "/", { scroll: false })
  }

  return (
    <Card className={cn("hairline-top border-border/80 bg-card/70 backdrop-blur-sm", className)}>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="space-y-1.5">
            <CardTitle className="text-lg">{title ?? scene}</CardTitle>
            {description && <CardDescription>{description}</CardDescription>}
          </div>
          <Badge className="border-border/80 bg-accent/60 text-foreground/80">
            {state.status === "done" ? "已完成" : state.status === "idle" ? "未开始" : `步骤 ${Math.max(state.step + 1, 0)} / ${total}`}
          </Badge>
        </div>
      </CardHeader>

      <Stepper
        steps={steps.map((s) => ({ title: s.title, description: s.description }))}
        current={state.step}
        done={showDone}
        onStepClick={(idx) => dispatch({ type: "SET_STEP", step: idx })}
      />

      <CardContent className="pt-4">
        {showDone ? (
          <div className="flex flex-col items-center gap-4 py-6 text-center">
            <div className="flex h-12 w-12 items-center justify-center rounded-full border border-emerald-500/40 bg-emerald-500/10">
              <Check className="h-6 w-6 text-emerald-500" />
            </div>
            <div className="space-y-1">
              <p className="text-base font-semibold text-foreground">流程已完成</p>
              <p className="text-xs text-muted-foreground">如需重新操作请重置 Wizard</p>
            </div>
            {doneActions}
          </div>
        ) : step ? (
          step.render({ state, dispatch, index: state.step })
        ) : null}
      </CardContent>

      <Separator />

      <CardFooter className="flex items-center justify-between border-t border-border/50 pt-4">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={!canPrev(state)}
          onClick={() => dispatch({ type: "PREV" })}
        >
          <ChevronLeft className="h-4 w-4" />
          上一步
        </Button>
        <span className="text-xs text-muted-foreground">
          {state.scene === null
            ? "未选择场景"
            : `${state.step + 1} / ${total}`}
        </span>
        {showDone ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
          onClick={handleReset}
          >
            重置
          </Button>
        ) : (
          <Button
            type="button"
            size="sm"
            disabled={total === 0}
            onClick={handleNext}
          >
            {isLastStep(state) ? "完成" : "下一步"}
            <ChevronRight className="h-4 w-4" />
          </Button>
        )}
      </CardFooter>
    </Card>
  )
}

interface StepperStepMeta {
  title: string
  description?: string
}

function Stepper({
  steps,
  current,
  done,
  onStepClick,
}: {
  steps: StepperStepMeta[]
  current: number
  done: boolean
  onStepClick: (index: number) => void
}) {
  return (
    <div className="mb-4">
      <ol className="flex items-stretch gap-2">
        {steps.map((s, idx) => {
          const isActive = idx === current && !done
          const isDone = done || idx < current
          return (
            <li key={idx} className="flex-1">
              <button
                type="button"
                disabled={done}
                onClick={() => onStepClick(idx)}
                className={cn(
                  "w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors",
                  isActive
                    ? "border-primary/50 bg-primary/10 text-foreground"
                    : isDone
                      ? "border-emerald-500/40 bg-emerald-500/5 text-foreground/90"
                      : "border-border/60 bg-background/40 text-muted-foreground hover:border-primary/30 hover:text-foreground",
                )}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "flex h-5 w-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-medium",
                      isDone
                        ? "border-emerald-500/60 bg-emerald-500/20 text-emerald-500"
                        : isActive
                          ? "border-primary/60 bg-primary/20 text-primary"
                          : "border-border bg-background/60 text-muted-foreground",
                    )}
                  >
                    {isDone ? <Check className="h-3 w-3" /> : idx + 1}
                  </span>
                  <span className="truncate font-medium">{s.title}</span>
                </div>
                {s.description && (
                  <p className="mt-1 truncate text-[10px] text-muted-foreground">
                    {s.description}
                  </p>
                )}
              </button>
            </li>
          )
        })}
      </ol>
    </div>
  )
}

function clampParse(raw: string, total: number): number {
  const n = Number.parseInt(raw, 10)
  if (Number.isNaN(n) || n < 0) return 0
  if (total <= 0) return 0
  return n > total - 1 ? total - 1 : n
}

/**
 * 场景卡片点击后跳转到带 query 的 URL；也可作为独立使用。
 */
export function SceneWizardLink({
  scene,
  href,
  children,
  className,
}: {
  scene: string
  href?: string
  children: React.ReactNode
  className?: string
}) {
  const target = href ?? `/?scene=${encodeURIComponent(scene)}`
  // eslint-disable-next-line @next/next/no-html-link-for-pages
  return (
    <a href={target} className={className}>
      {children}
    </a>
  )
}
