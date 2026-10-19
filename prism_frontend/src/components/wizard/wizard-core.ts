/**
 * Wizard 核心状态机。
 *
 * 设计目标：
 * 1. 纯 reducer，不依赖 React —— 便于单测；
 * 2. 状态数量与步骤数解耦（用 step index 表示当前步）；
 * 3. 支持 idle（未开始）/ stepping（进行中）/ done（已完成）三态；
 * 4. 提供 canNext / canPrev / isLast 等便捷判断；
 * 5. 与 URL query（?scene=xxx&step=N）同步由外部（wizard.tsx）负责。
 */

export type WizardStatus = "idle" | "stepping" | "done"

export interface WizardState {
  /** 场景 id，例如 "ai-writing" | "ai-image" | "video-pipeline" | "image-editor" */
  scene: string | null
  /** 当前步骤下标（0-based），scene 为 null 时无意义 */
  step: number
  /** 总步骤数（由 steps 数组长度决定） */
  total: number
  status: WizardStatus
}

export type WizardAction =
  | { type: "SELECT_SCENE"; scene: string; total: number; step?: number }
  | { type: "NEXT" }
  | { type: "PREV" }
  | { type: "SET_STEP"; step: number }
  | { type: "DONE" }
  | { type: "RESET" }
  | { type: "SYNC_FROM_URL"; scene: string; total: number; step: number; done: boolean }

export const INITIAL_WIZARD_STATE: WizardState = {
  scene: null,
  step: 0,
  total: 0,
  status: "idle",
}

/** clamp step 到 [0, total-1]，空 steps 时返回 0 */
export function clampStep(step: number, total: number): number {
  if (total <= 0) return 0
  if (step < 0) return 0
  if (step > total - 1) return total - 1
  return step
}

export function wizardReducer(
  state: WizardState,
  action: WizardAction,
): WizardState {
  switch (action.type) {
    case "SELECT_SCENE": {
      const total = Math.max(0, action.total)
      const step = clampStep(action.step ?? 0, total)
      return { scene: action.scene, step, total, status: total > 0 ? "stepping" : "idle" }
    }
    case "NEXT": {
      if (state.status === "done") return state
      const next = state.step + 1
      if (next >= state.total) {
        return { ...state, status: "done", step: state.total - 1 }
      }
      return { ...state, step: next, status: "stepping" }
    }
    case "PREV": {
      if (state.step <= 0) return state
      return { ...state, step: state.step - 1, status: "stepping" }
    }
    case "SET_STEP": {
      if (state.scene === null || state.total <= 0) return state
      return {
        ...state,
        step: clampStep(action.step, state.total),
        status: "stepping",
      }
    }
    case "DONE": {
      if (state.scene === null) return state
      return { ...state, status: "done", step: state.total - 1 }
    }
    case "RESET":
      return INITIAL_WIZARD_STATE
    default:
      return state
  }
}

export function canNext(state: WizardState): boolean {
  return state.status !== "done" && state.step < state.total - 1
}

export function canPrev(state: WizardState): boolean {
  return state.scene !== null && state.step > 0
}

export function isLastStep(state: WizardState): boolean {
  return state.total > 0 && state.step >= state.total - 1
}
