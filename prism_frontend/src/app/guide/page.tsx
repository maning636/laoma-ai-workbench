"use client"

import { Suspense } from "react"

import { PageHeader } from "@/components/layout/page-scaffold"
import { ScenarioGuide } from "@/components/wizard/scenario-guide"

/**
 * 快速开始（M4 功能引导独立路由）
 *
 * 背景：功能引导原先只内联在首页仪表盘里，靠 URL query `?scene=xxx` 切页，
 * 侧边栏没有任何入口指向它 —— 用户从首页卡片进过一次之后就再也找不回来。
 * 这里把同一套 ScenarioGuide 暴露成独立路由 /guide，场景 id 通过 ?scene= 传入，
 * 侧边栏「概览 → 快速开始」直接指向本页。
 */
export default function GuidePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="快速开始"
        description="选一个业务场景，按步骤走完写稿、生图、视频或图片编辑"
      />
      <Suspense fallback={null}>
        <ScenarioGuide />
      </Suspense>
    </div>
  )
}
