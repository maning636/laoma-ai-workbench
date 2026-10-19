import { describe, expect, it } from "vitest"
import {
  CROP_PRESETS,
  createHistory,
  getAspectValue,
  normalizeExportFormat,
  normalizePercentCrop,
  buildFilterCss,
} from "@/lib/image-editor-logic"

describe("CROP_PRESETS", () => {
  it("covers free + 5 common aspect ratios", () => {
    expect(CROP_PRESETS.map((p) => p.id)).toEqual(["free", "1:1", "3:4", "4:3", "16:9", "9:16"])
  })

  it("returns null ratio for free, correct values for others", () => {
    expect(getAspectValue("free")).toBeNull()
    expect(getAspectValue("1:1")).toBe(1)
    expect(getAspectValue("3:4")).toBeCloseTo(0.75)
    expect(getAspectValue("4:3")).toBeCloseTo(4 / 3)
    expect(getAspectValue("16:9")).toBeCloseTo(16 / 9)
    expect(getAspectValue("9:16")).toBeCloseTo(9 / 16)
  })
})

describe("createHistory (undo/redo)", () => {
  it("push/undo/redo cycles", () => {
    const h = createHistory(0)
    h.push(1)
    h.push(2)
    expect(h.canUndo()).toBe(true)
    expect(h.canRedo()).toBe(false)

    expect(h.undo()).toBe(1)
    expect(h.undo()).toBe(0)
    expect(h.canUndo()).toBe(false)

    expect(h.redo()).toBe(1)
    expect(h.redo()).toBe(2)
    expect(h.canRedo()).toBe(false)
  })

  it("new push truncates redo branch", () => {
    const h = createHistory("a")
    h.push("b")
    h.push("c")
    h.undo() // -> "b"
    h.push("z") // truncate redo "c"
    expect(h.canRedo()).toBe(false)
    expect(h.undo()).toBe("b")
    expect(h.undo()).toBe("a")
  })

  it("respects maxDepth", () => {
    const h = createHistory(0, 3)
    h.push(1); h.push(2); h.push(3); h.push(4); h.push(5)
    expect(h.getSnapshot().length).toBe(3)
    // top of stack should still be last pushed
    h.undo(); h.undo(); h.undo()
    // after popping down we should hit undefined at initial entry
    expect(h.getSnapshot()).toHaveLength(3)
  })

  it("clear resets to initial", () => {
    const h = createHistory("init")
    h.push("a")
    h.push("b")
    h.clear()
    expect(h.canUndo()).toBe(false)
    expect(h.canRedo()).toBe(false)
    expect(h.getSnapshot()).toEqual(["init"])
  })
})

describe("normalizePercentCrop", () => {
  it("clamps values to [0,1] and ensures bottom-right stays within bounds", () => {
    expect(normalizePercentCrop({ x: 0, y: 0, width: 2, height: 2 })).toEqual({
      x: 0, y: 0, width: 1, height: 1,
    })
    // Right/bottom overflow gets clipped (allow FP slack via toBeCloseTo)
    const clipped = normalizePercentCrop({ x: 0.8, y: 0.8, width: 0.5, height: 0.5 })
    expect(clipped.x).toBeCloseTo(0.8)
    expect(clipped.y).toBeCloseTo(0.8)
    expect(clipped.width).toBeCloseTo(0.2)
    expect(clipped.height).toBeCloseTo(0.2)
  })

  it("defaults to a sensible 80% central crop when values are missing", () => {
    const result = normalizePercentCrop({})
    expect(result.width).toBeCloseTo(0.8)
    expect(result.height).toBeCloseTo(0.8)
  })

  it("treats NaN as 0", () => {
    expect(normalizePercentCrop({ x: Number.NaN, y: Number.NaN, width: Number.NaN, height: Number.NaN }))
      .toEqual({ x: 0, y: 0, width: 0.8, height: 0.8 })
  })
})

describe("normalizeExportFormat", () => {
  it("accepts canonical and legacy aliases", () => {
    expect(normalizeExportFormat("image/png")).toBe("image/png")
    expect(normalizeExportFormat("png")).toBe("image/png")
    expect(normalizeExportFormat("image/jpeg")).toBe("image/jpeg")
    expect(normalizeExportFormat("jpg")).toBe("image/jpeg")
    expect(normalizeExportFormat("image/webp")).toBe("image/webp")
  })

  it("rejects unknown formats", () => {
    expect(() => normalizeExportFormat("image/bmp")).toThrow(/Unsupported export format/)
  })
})

describe("buildFilterCss", () => {
  it("formats brightness/contrast/saturation percentages", () => {
    expect(buildFilterCss({ brightness: 120, contrast: 90, saturation: 130 }))
      .toBe("brightness(120%) contrast(90%) saturate(130%)")
  })

  it("clamps negative saturation to 0 (canvas saturate rejects negatives)", () => {
    expect(buildFilterCss({ brightness: 100, contrast: 100, saturation: -50 }))
      .toBe("brightness(100%) contrast(100%) saturate(0%)")
  })
})
