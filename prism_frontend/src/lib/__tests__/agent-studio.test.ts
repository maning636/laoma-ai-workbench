import { describe, expect, it } from "vitest"
import {
  AGENT_LIMITS,
  EMPTY_FORM,
  buildCreatePayload,
  quotaUI,
  summarizeStylePrompt,
  validateAgentForm,
} from "../agent-studio"

describe("AGENT_LIMITS — 与后端 & 澜途对齐", () => {
  it("名称上限 80", () => {
    expect(AGENT_LIMITS.nameMax).toBe(80)
  })
  it("描述上限 500", () => {
    expect(AGENT_LIMITS.descriptionMax).toBe(500)
  })
  it("设计原则上限 12000（澜途硬上限）", () => {
    expect(AGENT_LIMITS.designPrinciplesMax).toBe(12000)
  })
})

describe("EMPTY_FORM", () => {
  it("初始状态四字段全空", () => {
    expect(EMPTY_FORM).toEqual({
      name: "",
      description: "",
      sample_contents: "",
      design_principles: "",
    })
  })
})

describe("validateAgentForm — 必填校验", () => {
  it("空表单：name + sample_contents 都有错", () => {
    const v = validateAgentForm(EMPTY_FORM)
    expect(v.ok).toBe(false)
    expect(v.errors.name).toMatch(/名称/)
    expect(v.errors.sample_contents).toMatch(/样例/)
  })

  it("只有名称，样例为空 → 只报样例错", () => {
    const v = validateAgentForm({ ...EMPTY_FORM, name: "Test" })
    expect(v.ok).toBe(false)
    expect(v.errors.name).toBeUndefined()
    expect(v.errors.sample_contents).toBeDefined()
  })

  it("合法表单 → ok", () => {
    const v = validateAgentForm({
      name: "冷色调海报",
      description: "极简",
      sample_contents: "标题：新品上市\n正文：三款夏日新品已上架",
      design_principles: "主色蓝紫",
    })
    expect(v.ok).toBe(true)
    expect(Object.keys(v.errors)).toHaveLength(0)
  })
})

describe("validateAgentForm — 长度校验", () => {
  it("name 超过 80 字报错", () => {
    const v = validateAgentForm({
      ...EMPTY_FORM,
      name: "x".repeat(81),
      sample_contents: "s",
    })
    expect(v.ok).toBe(false)
    expect(v.errors.name).toMatch(/80/)
  })

  it("description 超过 500 字报错", () => {
    const v = validateAgentForm({
      ...EMPTY_FORM,
      name: "A",
      description: "x".repeat(501),
      sample_contents: "s",
    })
    expect(v.ok).toBe(false)
    expect(v.errors.description).toMatch(/500/)
  })

  it("design_principles 超过 12000 字报错", () => {
    const v = validateAgentForm({
      ...EMPTY_FORM,
      name: "A",
      sample_contents: "s",
      design_principles: "x".repeat(12001),
    })
    expect(v.ok).toBe(false)
    expect(v.errors.design_principles).toMatch(/12000/)
  })

  it("边界值（== 上限）不报错", () => {
    const v = validateAgentForm({
      name: "x".repeat(80),
      description: "y".repeat(500),
      sample_contents: "s",
      design_principles: "z".repeat(12000),
    })
    expect(v.ok).toBe(true)
  })
})

describe("buildCreatePayload — 请求体构造", () => {
  it("空表单 → null", () => {
    expect(buildCreatePayload(EMPTY_FORM)).toBeNull()
  })

  it("名称为空 → null", () => {
    expect(buildCreatePayload({ ...EMPTY_FORM, sample_contents: "s" })).toBeNull()
  })

  it("样例全空行 → null", () => {
    expect(buildCreatePayload({
      ...EMPTY_FORM,
      name: "A",
      sample_contents: "   \n\n  \t ",
    })).toBeNull()
  })

  it("合法输入：多行样例被拆成数组 + 空白被裁剪", () => {
    const p = buildCreatePayload({
      name: "  Test  ",
      description: "  desc  ",
      sample_contents: "标题A\n\n标题B\n标题C",
      design_principles: "  主色  ",
    })
    expect(p).not.toBeNull()
    expect(p!.name).toBe("Test")
    expect(p!.description).toBe("desc")
    expect(p!.sample_contents).toEqual(["标题A", "标题B", "标题C"])
    expect(p!.design_principles).toBe("主色")
  })

  it("单行样例 → 单元素数组", () => {
    const p = buildCreatePayload({
      ...EMPTY_FORM,
      name: "A",
      sample_contents: "hello world",
    })
    expect(p!.sample_contents).toEqual(["hello world"])
  })
})

describe("quotaUI — 配额显示与按钮状态", () => {
  it("0/2 未超限 → 可创建", () => {
    const ui = quotaUI({ limit: 2, used: 0, canCreate: true, upgrade_url: "/billing/upgrade" })
    expect(ui.disabled).toBe(false)
    expect(ui.label).toBe("0/2")
    expect(ui.showUpgrade).toBe(false)
  })

  it("2/2 已满 → 禁用创建 + 显示升级提示", () => {
    const ui = quotaUI({ limit: 2, used: 2, canCreate: false, upgrade_url: "/billing/upgrade" })
    expect(ui.disabled).toBe(true)
    expect(ui.label).toBe("2/2")
    expect(ui.showUpgrade).toBe(true)
  })

  it("quota 为 null（加载中）→ 禁用 + 显示占位", () => {
    const ui = quotaUI(null)
    expect(ui.disabled).toBe(true)
    expect(ui.label).toBe("…")
    expect(ui.showUpgrade).toBe(false)
  })

  it("已满但无升级链接 → 不显示升级提示", () => {
    const ui = quotaUI({ limit: 2, used: 2, canCreate: false, upgrade_url: "" })
    expect(ui.disabled).toBe(true)
    expect(ui.showUpgrade).toBe(false)
  })

  it("自定义 limit（付费用户）5/5", () => {
    const ui = quotaUI({ limit: 5, used: 5, canCreate: false, upgrade_url: "/x" })
    expect(ui.label).toBe("5/5")
    expect(ui.disabled).toBe(true)
  })
})

describe("summarizeStylePrompt — 卡片摘要", () => {
  it("空字符串 → 占位提示", () => {
    expect(summarizeStylePrompt("")).toMatch(/无 style_prompt/)
    expect(summarizeStylePrompt("   ")).toMatch(/无 style_prompt/)
  })

  it("短字符串原样返回", () => {
    expect(summarizeStylePrompt("Tone: 简洁")).toBe("Tone: 简洁")
  })

  it("长字符串按 maxLen 截断 + 省略号", () => {
    const s = "x".repeat(200)
    const out = summarizeStylePrompt(s, 50)
    expect(out).toHaveLength(51) // 50 + "…"
    expect(out.endsWith("…")).toBe(true)
  })

  it("默认 maxLen=80", () => {
    const out = summarizeStylePrompt("y".repeat(100))
    expect(out).toHaveLength(81) // 80 + "…"
  })
})
