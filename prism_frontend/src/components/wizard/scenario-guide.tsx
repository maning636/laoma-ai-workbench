"use client"

import { Suspense } from "react"
import { useSearchParams, useRouter } from "next/navigation"

import { ArrowLeft, ArrowRight, Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Wizard } from "./wizard"
import {
  ScenarioGrid,
  getScenarioById,
  type ScenarioDefinition,
} from "./scenarios"

/**
 * 首页功能引导区（M4）
 *
 * 行为：
 * - URL 无 ?scene=xxx：显示 4 张场景卡片；
 * - URL 带 ?scene=xxx：显示对应场景的 Wizard；
 * - 点击场景卡片 → router.push 到 /?scene=<id>；
 * - 完成 Wizard → 跳转场景 target 路径。
 */
export function ScenarioGuide() {
  // M4 hardening：`useSearchParams` 需要 Suspense 包裹（Next.js 16 SSR warning）
  return (
    <Suspense fallback={null}>
      <ScenarioGuideContent />
    </Suspense>
  )
}

function ScenarioGuideContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const sceneParam = searchParams.get("scene")
  const activeScenario = sceneParam ? getScenarioById(sceneParam) : undefined

  const handleStart = (scenario: ScenarioDefinition) => {
    router.push(`/?scene=${encodeURIComponent(scenario.id)}`)
  }

  const handleExit = () => router.push("/")

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-0.5 text-[10px] uppercase tracking-[0.12em] text-primary">
            <Sparkles className="h-3 w-3" />
            功能引导
          </div>
          <h2 className="text-lg font-semibold text-foreground">
            选择业务场景，按步骤快速开始
          </h2>
          <p className="text-xs text-muted-foreground">
            {activeScenario
              ? `正在进入「${activeScenario.title}」流程，共 ${activeScenario.steps.length} 步`
              : "4 大核心场景覆盖写稿、生图、视频、图片编辑"}
          </p>
        </div>
        {activeScenario ? (
          <Button
            variant="ghost"
            size="sm"
            className="gap-1.5 text-xs text-foreground/70 hover:text-foreground"
            onClick={handleExit}
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            返回场景列表
          </Button>
        ) : null}
      </div>

      {activeScenario ? (
        <ScenarioWizardBlock scenario={activeScenario} router={router} />
      ) : (
        <ScenarioGrid onStart={handleStart} />
      )}
    </section>
  )
}

function ScenarioWizardBlock({
  scenario,
  router,
}: {
  scenario: ScenarioDefinition
  router: ReturnType<typeof useRouter>
}) {
  // onComplete 仅用于自动跳走的场景（如 image-editor）；
  // 其他场景在 done 视图里保留手动跳转按钮。
  const handleComplete = () => {
    // image-editor 场景只有一步，完成即视为进入编辑器
    if (scenario.id === "image-editor") {
      router.push(scenario.target)
    }
  }

  return (
    <Wizard
      scene={scenario.id}
      title={scenario.title}
      description={scenario.description}
      steps={scenario.steps}
      onComplete={handleComplete}
      doneActions={
        scenario.id === "image-editor" ? undefined : (
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => router.push("/")}
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              返回场景列表
            </Button>
            <Button
              type="button"
              size="sm"
              onClick={() => router.push(scenario.target)}
            >
              进入「{scenario.title}」
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        )
      }
    />
  )
}
