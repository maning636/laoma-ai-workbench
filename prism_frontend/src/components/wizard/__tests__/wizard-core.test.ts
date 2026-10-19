import { describe, expect, it } from "vitest"
import {
  INITIAL_WIZARD_STATE,
  canNext,
  canPrev,
  clampStep,
  isLastStep,
  wizardReducer,
  type WizardState,
} from "../wizard-core"

function seeded(scene = "ai-writing", total = 4, step = 0): WizardState {
  return { scene, step, total, status: "stepping" }
}

describe("wizardReducer — SELECT_SCENE", () => {
  it("starts from idle and enters stepping with correct total", () => {
    const s = wizardReducer(INITIAL_WIZARD_STATE, {
      type: "SELECT_SCENE",
      scene: "ai-writing",
      total: 4,
    })
    expect(s).toEqual({
      scene: "ai-writing",
      step: 0,
      total: 4,
      status: "stepping",
    })
  })

  it("clamps requested step when > total-1", () => {
    const s = wizardReducer(INITIAL_WIZARD_STATE, {
      type: "SELECT_SCENE",
      scene: "ai-image",
      total: 3,
      step: 99,
    })
    expect(s.step).toBe(2)
  })

  it("clamps requested step when < 0", () => {
    const s = wizardReducer(INITIAL_WIZARD_STATE, {
      type: "SELECT_SCENE",
      scene: "ai-image",
      total: 3,
      step: -1,
    })
    expect(s.step).toBe(0)
  })

  it("total=0 keeps idle status", () => {
    const s = wizardReducer(INITIAL_WIZARD_STATE, {
      type: "SELECT_SCENE",
      scene: "empty",
      total: 0,
    })
    expect(s.status).toBe("idle")
    expect(s.step).toBe(0)
  })
})

describe("wizardReducer — NEXT", () => {
  it("advances step while under the last", () => {
    expect(wizardReducer(seeded(), { type: "NEXT" })).toMatchObject({
      step: 1,
      status: "stepping",
    })
  })

  it("on last step transitions to done (step remains)", () => {
    const last = seeded("ai-writing", 4, 3)
    const s = wizardReducer(last, { type: "NEXT" })
    expect(s.step).toBe(3)
    expect(s.status).toBe("done")
  })

  it("is a no-op when already done", () => {
    const done = { scene: "x", step: 3, total: 4, status: "done" as const }
    expect(wizardReducer(done, { type: "NEXT" }).status).toBe("done")
  })
})

describe("wizardReducer — PREV", () => {
  it("goes back one step", () => {
    const s = wizardReducer(seeded("ai-writing", 4, 2), { type: "PREV" })
    expect(s.step).toBe(1)
    expect(s.status).toBe("stepping")
  })

  it("is a no-op at step 0", () => {
    expect(wizardReducer(seeded("x", 3, 0), { type: "PREV" }).step).toBe(0)
  })
})

describe("wizardReducer — SET_STEP", () => {
  it("jumps to arbitrary step and clamps", () => {
    const s = wizardReducer(seeded("x", 3, 0), { type: "SET_STEP", step: 10 })
    expect(s.step).toBe(2)
  })

  it("is a no-op when no scene selected", () => {
    expect(wizardReducer(INITIAL_WIZARD_STATE, { type: "SET_STEP", step: 2 })).toEqual(
      INITIAL_WIZARD_STATE,
    )
  })
})

describe("wizardReducer — DONE / RESET", () => {
  it("DONE forces status and last step", () => {
    const s = wizardReducer(seeded("x", 5, 2), { type: "DONE" })
    expect(s.status).toBe("done")
    expect(s.step).toBe(4)
  })

  it("RESET returns to initial idle state", () => {
    const s = wizardReducer(seeded("x", 5, 3), { type: "RESET" })
    expect(s).toEqual(INITIAL_WIZARD_STATE)
  })
})

describe("wizardReducer — SYNC_FROM_URL (implicit via SET_STEP + DONE)", () => {
  it("simulates URL restore: scene=ai-writing&step=2&done=1", () => {
    let s = seeded("ai-writing", 4, 0)
    s = wizardReducer(s, { type: "SET_STEP", step: 2 })
    s = wizardReducer(s, { type: "DONE" })
    expect(s).toMatchObject({ step: 3, status: "done" })
  })
})

describe("helper predicates", () => {
  it("canNext false at last step / when done", () => {
    expect(canNext(seeded("x", 4, 2))).toBe(true)
    expect(canNext(seeded("x", 4, 3))).toBe(false)
    expect(canNext({ ...seeded("x", 4, 3), status: "done" })).toBe(false)
  })

  it("canPrev false at step 0 or no scene", () => {
    expect(canPrev(seeded("x", 4, 0))).toBe(false)
    expect(canPrev(seeded("x", 4, 2))).toBe(true)
    expect(canPrev(INITIAL_WIZARD_STATE)).toBe(false)
  })

  it("isLastStep true when step === total-1", () => {
    expect(isLastStep(seeded("x", 4, 3))).toBe(true)
    expect(isLastStep(seeded("x", 4, 2))).toBe(false)
    expect(isLastStep(INITIAL_WIZARD_STATE)).toBe(false)
  })
})

describe("clampStep", () => {
  it("bounds to [0, total-1]", () => {
    expect(clampStep(-5, 4)).toBe(0)
    expect(clampStep(0, 4)).toBe(0)
    expect(clampStep(2, 4)).toBe(2)
    expect(clampStep(99, 4)).toBe(3)
  })
  it("handles total<=0", () => {
    expect(clampStep(3, 0)).toBe(0)
    expect(clampStep(-1, -1)).toBe(0)
  })
})
