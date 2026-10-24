// @vitest-environment jsdom
import * as React from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act, cleanup, render } from "@testing-library/react"

import {
  DEDUPE_MAX_COUNT,
  toast,
  TOAST_LIMIT,
  useToast,
} from "@/components/ui/use-toast"

/**
 * useToast 同 dedupeKey 去重 + 限流回归测试。
 *
 * 覆盖：
 *   - 同 dedupeKey 连续 5 次调用 → 只保留 1 条活跃 toast
 *   - count 到达 DEDUPE_MAX_COUNT(=3) 后不再刷新，后续调用直接丢弃
 *   - 徽标：count=1 无徽标、count=2 显示 ×2、count=3 显示 ×3
 *   - 不同 dedupeKey 各自独立
 *   - TOAST_LIMIT=2：不同 dedupeKey 累积不超过 2 条
 *   - 无 dedupeKey 的 toast 保持原行为
 *
 * 说明：Radix Toast.Root 在 jsdom 下会通过 compose-refs / ProviderContext
 * 触发 setState 形成无限更新循环，因此这里不渲染真实 <Toaster />，而是
 * 用 BadgeProbe 组件直接读取 useToast().toasts，既验证 state 又验证
 * 与真实 toaster.tsx 一致的 "×N" 徽标渲染逻辑。
 */

function StateProbe() {
  const { toasts } = useToast()
  return (
    <div
      data-testid="state-probe"
      data-count={toasts.length}
      data-counts={toasts
        .map((t) => t.count ?? 0)
        .join(",")}
      data-ids={toasts.map((t) => t.id).join(",")}
      data-keys={toasts.map((t) => t.dedupeKey ?? "").join(",")}
    />
  )
}

/**
 * 与 toaster.tsx 里 "×N" 徽标渲染逻辑对齐的最小组件。
 * 仅用于验证 count > 1 时 UI 上会出现 ×N 徽标；不重复实现 toaster 其余部分。
 */
function BadgeProbe() {
  const { toasts } = useToast()
  return (
    <div data-testid="badge-probe">
      {toasts.map((t) => {
        const showCount = typeof t.count === "number" && t.count > 1
        return (
          <div key={t.id}>
            <span>{t.title}</span>
            {showCount ? <span data-testid="count-badge">×{t.count}</span> : null}
          </div>
        )
      })}
    </div>
  )
}

function CleanupHook() {
  const { dismiss } = useToast()
  // dismiss 每次 render 都是新函数，不能作为 useEffect 依赖（会形成
  // cleanup → dispatch → re-render → cleanup 无限循环）。
  // 用 ref 保存最新 dismiss，effect 依赖空数组，仅 unmount 时调用一次。
  const dismissRef = React.useRef(dismiss)
  React.useEffect(() => {
    dismissRef.current = dismiss
  })
  React.useEffect(
    () => () => {
      // unmount 时清空 dedupeState，避免跨用例污染。
      // dismiss() 无参 = dispatch DISMISS_TOAST(toastId=undefined) →
      // 全部 open=false + 逐个 addToRemoveQueue + cleanDedupeEntry。
      dismissRef.current()
    },
    []
  )
  return null
}

function TestHarness() {
  return (
    <>
      <CleanupHook />
      <StateProbe />
      <BadgeProbe />
    </>
  )
}

function readProbe() {
  return document.querySelector("[data-testid='state-probe']") as HTMLElement | null
}

function fireToast(props: Parameters<typeof toast>[0]) {
  // toast() 内部 dispatch → listener setState → React 会同步 re-render。
  // 用 act 包裹确保 re-render 完成后再读 DOM。
  act(() => {
    toast(props)
  })
}

beforeEach(() => {
  // 使用 fake timers 控制 setTimeout（addToRemoveQueue 走 1s 延迟 REMOVE_TOAST，
  // 自动 dismiss 走 4s duration）。React 18 用 MessageChannel 调度渲染，
  // 不受 fake timers 影响，因此 act() 正常工作。
  vi.useFakeTimers()
})

afterEach(() => {
  // 跑完所有 pending timers：自动 dismiss (4s) → dismissToastById →
  // addToRemoveQueue (1s) → REMOVE_TOAST，确保 memoryState 清空。
  act(() => {
    vi.runAllTimers()
  })
  vi.useRealTimers()
  cleanup()
})

describe("useToast 同 dedupeKey 去重与限流", () => {
  it("连续 5 次同 dedupeKey 失败：只保留 1 条 toast，count 到 DEDUPE_MAX_COUNT 后丢弃", () => {
    render(<TestHarness />)

    // 前 3 次：分别触发新增 / count=2 / count=3
    for (let i = 0; i < 3; i++) {
      fireToast({
        title: "配置读取失败",
        description: "网络错误",
        variant: "destructive",
        dedupeKey: "chat-config-load-failed",
      })
    }
    const probe3 = readProbe()!
    expect(probe3.getAttribute("data-count")).toBe("1")
    expect(probe3.getAttribute("data-counts")).toBe(String(DEDUPE_MAX_COUNT))

    // 再触发 2 次：应被丢弃，count 保持 3，队列长度保持 1
    fireToast({
      title: "配置读取失败",
      description: "网络错误",
      variant: "destructive",
      dedupeKey: "chat-config-load-failed",
    })
    fireToast({
      title: "配置读取失败",
      description: "网络错误",
      variant: "destructive",
      dedupeKey: "chat-config-load-failed",
    })
    const probe5 = readProbe()!
    expect(probe5.getAttribute("data-count")).toBe("1")
    expect(probe5.getAttribute("data-counts")).toBe(String(DEDUPE_MAX_COUNT))
    expect(probe5.getAttribute("data-ids")!.split(",").length).toBe(1)
  })

  it("count 计数徽标：count=1 无徽标，count=2 显示 ×2，count=3 显示 ×3", () => {
    render(<TestHarness />)

    fireToast({ title: "第一次", dedupeKey: "count-badge" })
    expect(document.body.textContent).not.toMatch(/×2/)
    expect(document.body.textContent).not.toMatch(/×3/)

    fireToast({ title: "第二次", dedupeKey: "count-badge" })
    expect(document.body.textContent).toMatch(/×2/)

    fireToast({ title: "第三次", dedupeKey: "count-badge" })
    expect(document.body.textContent).toMatch(/×3/)
    // 第 4 次不新增、count 保持 3
    fireToast({ title: "第四次", dedupeKey: "count-badge" })
    expect(document.body.textContent).not.toMatch(/×4/)
  })

  it("不同 dedupeKey 各自独立；TOAST_LIMIT=2 生效", () => {
    render(<TestHarness />)

    fireToast({ title: "A", dedupeKey: "a" })
    fireToast({ title: "B", dedupeKey: "b" })

    const probe2 = readProbe()!
    expect(probe2.getAttribute("data-count")).toBe(String(TOAST_LIMIT))
    expect(probe2.getAttribute("data-keys")!.split(",")).toHaveLength(2)

    // 第三个不同 key：会挤压掉最早的，dedupeState 应随之清理
    fireToast({ title: "C", dedupeKey: "c" })
    const probe3 = readProbe()!
    expect(probe3.getAttribute("data-count")).toBe(String(TOAST_LIMIT))

    // 挤压后：再次调用 'a'，因为旧条目已被清理，应视为新 toast（count=1）
    // 但由于 'c' 和 'b' 已占满，会再次挤压 'b'。
    fireToast({ title: "A again", dedupeKey: "a" })
    const probe4 = readProbe()!
    expect(probe4.getAttribute("data-count")).toBe(String(TOAST_LIMIT))
    // 最新一条应是 'a'
    expect(probe4.getAttribute("data-keys")!.split(",")[0]).toBe("a")
  })

  it("无 dedupeKey 的 toast 保持原行为：连续 5 条只保留 TOAST_LIMIT 条", () => {
    render(<TestHarness />)

    for (let i = 0; i < 5; i++) {
      fireToast({ title: `#${i}` })
    }
    const probe = readProbe()!
    expect(probe.getAttribute("data-count")).toBe(String(TOAST_LIMIT))
  })
})
