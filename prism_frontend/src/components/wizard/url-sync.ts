import type { WizardState } from "./wizard-core"

/**
 * URL query 同步工具（纯函数）。
 *
 * Wizard 组件把 ?scene=xxx&step=N&done=1 与 reducer state 双向同步，
 * 这里抽出成纯函数便于单测；组件侧直接调用即可。
 */

/** URL 中表示 Wizard 状态的三个 query key */
export const WIZARD_QUERY_KEYS = {
  scene: "scene",
  step: "step",
  done: "done",
} as const

export type WizardQueryPatch = {
  scene?: string | null
  step?: number | null
  done?: boolean | null
}

/** clampParse 与组件内实现一致，抽出来便于复用 */
export function clampParseStep(raw: string | null | undefined, total: number): number {
  if (raw == null) return 0
  const n = Number.parseInt(raw, 10)
  if (Number.isNaN(n) || n < 0) return 0
  if (total <= 0) return 0
  return n > total - 1 ? total - 1 : n
}

/** 从 URLSearchParams 解析 Wizard 状态 */
export function parseWizardQuery(
  sp: URLSearchParams,
  total: number,
): Pick<WizardState, "step" | "status"> & { scene: string | null } {
  const scene = sp.get(WIZARD_QUERY_KEYS.scene)
  const step = clampParseStep(sp.get(WIZARD_QUERY_KEYS.step), total)
  const done = sp.get(WIZARD_QUERY_KEYS.done) === "1"
  return {
    scene,
    step: done && total > 0 ? total - 1 : step,
    status: total === 0 ? "idle" : done ? "done" : "stepping",
  }
}

/** 把 Wizard 状态同步到 URLSearchParams（返回新实例，不修改原对象） */
export function buildWizardQuery(
  base: URLSearchParams,
  patch: WizardQueryPatch,
): URLSearchParams {
  const sp = new URLSearchParams(base.toString())

  if (patch.scene != null) {
    if (patch.scene === "") sp.delete(WIZARD_QUERY_KEYS.scene)
    else sp.set(WIZARD_QUERY_KEYS.scene, patch.scene)
  }
  if (patch.step != null) {
    sp.set(WIZARD_QUERY_KEYS.step, String(Math.max(patch.step, 0)))
  } else if (patch.scene === "") {
    sp.delete(WIZARD_QUERY_KEYS.step)
  }
  if (patch.done != null) {
    if (patch.done) sp.set(WIZARD_QUERY_KEYS.done, "1")
    else sp.delete(WIZARD_QUERY_KEYS.done)
  } else if (patch.scene === "") {
    sp.delete(WIZARD_QUERY_KEYS.done)
  }
  return sp
}

/** 是否处于 Wizard 模式（URL 携带 scene） */
export function hasWizardQuery(sp: URLSearchParams): boolean {
  return sp.get(WIZARD_QUERY_KEYS.scene) != null
}
