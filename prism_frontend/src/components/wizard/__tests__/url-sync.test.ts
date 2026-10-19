import { describe, expect, it } from "vitest"
import {
  WIZARD_QUERY_KEYS,
  buildWizardQuery,
  clampParseStep,
  hasWizardQuery,
  parseWizardQuery,
} from "../url-sync"

describe("WIZARD_QUERY_KEYS", () => {
  it("暴露三个稳定 key 供组件与测试共用", () => {
    expect(WIZARD_QUERY_KEYS).toEqual({ scene: "scene", step: "step", done: "done" })
  })
})

describe("clampParseStep", () => {
  it("空/非数字/负数 → 0", () => {
    expect(clampParseStep(null, 4)).toBe(0)
    expect(clampParseStep(undefined, 4)).toBe(0)
    expect(clampParseStep("abc", 4)).toBe(0)
    expect(clampParseStep("-3", 4)).toBe(0)
  })
  it("越界 → total-1；total<=0 → 0", () => {
    expect(clampParseStep("99", 4)).toBe(3)
    expect(clampParseStep("5", 0)).toBe(0)
    expect(clampParseStep("5", -1)).toBe(0)
  })
})

describe("parseWizardQuery (URL → state)", () => {
  it("正常解析 scene + step", () => {
    const r = parseWizardQuery(
      new URLSearchParams("scene=ai-writing&step=2"),
      4,
    )
    expect(r).toEqual({
      scene: "ai-writing",
      step: 2,
      status: "stepping",
    })
  })

  it("done=1 时 status=done，step 钳到 total-1", () => {
    const r = parseWizardQuery(
      new URLSearchParams("scene=x&step=2&done=1"),
      4,
    )
    expect(r.status).toBe("done")
    expect(r.step).toBe(3)
  })

  it("无 scene → scene=null", () => {
    expect(parseWizardQuery(new URLSearchParams("step=2"), 4).scene).toBeNull()
  })

  it("total=0 → status=idle", () => {
    expect(parseWizardQuery(new URLSearchParams("scene=x"), 0).status).toBe("idle")
  })
})

describe("buildWizardQuery (state → URL)", () => {
  it("初始空 query → step=2&done=1", () => {
    const out = buildWizardQuery(new URLSearchParams(""), {
      step: 2,
      done: true,
    })
    expect(out.toString()).toBe("step=2&done=1")
  })

  it("保留其他 query 键", () => {
    const base = new URLSearchParams("q=hello&foo=bar")
    const out = buildWizardQuery(base, { step: 1, done: false })
    expect(out.get("q")).toBe("hello")
    expect(out.get("foo")).toBe("bar")
    expect(out.get("step")).toBe("1")
    expect(out.get("done")).toBeNull()
  })

  it("done=false 时移除 done 键", () => {
    const base = new URLSearchParams("done=1&step=3")
    const out = buildWizardQuery(base, { done: false })
    expect(out.get("done")).toBeNull()
  })

  it("scene='' 触发 RESET：删除 scene/step/done", () => {
    const base = new URLSearchParams("scene=x&step=1&done=1&keep=1")
    const out = buildWizardQuery(base, { scene: "" })
    expect(out.get("scene")).toBeNull()
    expect(out.get("step")).toBeNull()
    expect(out.get("done")).toBeNull()
    expect(out.get("keep")).toBe("1")
  })
})

describe("hasWizardQuery", () => {
  it("有 scene → true", () => {
    expect(hasWizardQuery(new URLSearchParams("scene=ai-writing"))).toBe(true)
  })
  it("无 scene → false", () => {
    expect(hasWizardQuery(new URLSearchParams("step=2"))).toBe(false)
  })
})
