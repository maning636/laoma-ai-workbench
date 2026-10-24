"use client"

import * as React from "react"

import type { ToastActionElement, ToastProps } from "@/components/ui/toaster"

const TOAST_LIMIT = 2
const TOAST_REMOVE_DELAY = 1000
// 同 dedupeKey 的活跃 toast 允许被重复刷新的最大次数；
// 达到上限后不再重置，后续调用直接丢弃，防止高频错误刷屏。
const DEDUPE_MAX_COUNT = 3

type ToasterToast = ToastProps & {
  id: string
  title?: React.ReactNode
  description?: React.ReactNode
  action?: ToastActionElement
  /** 同 key 去重标识；非必填。同一 dedupeKey 的活跃 toast 会被合并而非堆叠。 */
  dedupeKey?: string
  /** 同 dedupeKey 累计出现次数；仅 dedupe 场景下递增。 */
  count?: number
}

const actionTypes = {
  ADD_TOAST: "ADD_TOAST",
  UPDATE_TOAST: "UPDATE_TOAST",
  DISMISS_TOAST: "DISMISS_TOAST",
  REMOVE_TOAST: "REMOVE_TOAST",
} as const

type ActionType = typeof actionTypes

type Action =
  | { type: ActionType["ADD_TOAST"]; toast: ToasterToast }
  | { type: ActionType["UPDATE_TOAST"]; toast: Partial<ToasterToast> & Pick<ToasterToast, "id"> }
  | { type: ActionType["DISMISS_TOAST"]; toastId?: ToasterToast["id"] }
  | { type: ActionType["REMOVE_TOAST"]; toastId?: ToasterToast["id"] }

interface State {
  toasts: ToasterToast[]
}

const toastTimeouts = new Map<string, ReturnType<typeof setTimeout>>()

const addToRemoveQueue = (toastId: string) => {
  if (toastTimeouts.has(toastId)) {
    return
  }

  const timeout = setTimeout(() => {
    toastTimeouts.delete(toastId)
    dispatch({
      type: "REMOVE_TOAST",
      toastId,
    })
  }, TOAST_REMOVE_DELAY)

  toastTimeouts.set(toastId, timeout)
}

const reducer = (state: State, action: Action): State => {
  switch (action.type) {
    case actionTypes.ADD_TOAST:
      return {
        ...state,
        toasts: [action.toast, ...state.toasts].slice(0, TOAST_LIMIT),
      }
    case actionTypes.UPDATE_TOAST:
      return {
        ...state,
        toasts: state.toasts.map((toast) =>
          toast.id === action.toast.id ? { ...toast, ...action.toast } : toast
        ),
      }
    case actionTypes.DISMISS_TOAST:
      return {
        ...state,
        toasts: state.toasts.map((toast) =>
          toast.id === action.toastId || action.toastId === undefined ? { ...toast, open: false } : toast
        ),
      }
    case actionTypes.REMOVE_TOAST:
      if (action.toastId === undefined) {
        return { ...state, toasts: [] }
      }
      return {
        ...state,
        toasts: state.toasts.filter((toast) => toast.id !== action.toastId),
      }
    default:
      return state
  }
}

const listeners = new Set<(state: State) => void>()
let memoryState: State = { toasts: [] }

function dispatch(action: Action) {
  memoryState = reducer(memoryState, action)
  listeners.forEach((listener) => listener(memoryState))
}

// dedupeKey → 活跃 toast 元数据。同一 dedupeKey 同一时刻只保留一条。
type DedupeEntry = {
  id: string
  count: number
  autoDismissTimer: ReturnType<typeof setTimeout> | null
}
const dedupeState = new Map<string, DedupeEntry>()

function cleanDedupeEntry(toastId: string) {
  for (const [key, entry] of dedupeState) {
    if (entry.id === toastId) {
      if (entry.autoDismissTimer) clearTimeout(entry.autoDismissTimer)
      dedupeState.delete(key)
      break
    }
  }
}

function updateToastById(id: string, props: Partial<ToasterToast>) {
  dispatch({
    type: actionTypes.UPDATE_TOAST,
    toast: { ...props, id },
  })
}

function dismissToastById(id: string) {
  dispatch({ type: actionTypes.DISMISS_TOAST, toastId: id })
  addToRemoveQueue(id)
  cleanDedupeEntry(id)
}

type Toast = Omit<ToasterToast, "id">

function toast({ ...props }: Toast) {
  const duration = props.duration ?? 4000

  // 同 dedupeKey 已存在活跃 toast：不再新增，仅更新内容与计时；
  // 计数达到 DEDUPE_MAX_COUNT 后直接丢弃，避免高频错误刷屏。
  // 若 existing.id 已不在活跃 state（例如被 TOAST_LIMIT 挤出或正在 fadeout），
  // 视为孤儿条目，丢弃并走新建路径。
  if (props.dedupeKey) {
    const existing = dedupeState.get(props.dedupeKey)
    const isAlive = existing && memoryState.toasts.some((t) => t.id === existing.id)
    if (isAlive) {
      if (existing.count >= DEDUPE_MAX_COUNT) {
        return {
          id: existing.id,
          dismiss: () => dismissToastById(existing.id),
          update: (u: ToasterToast) => updateToastById(existing.id, u),
        }
      }
      const nextCount = existing.count + 1
      existing.count = nextCount
      if (existing.autoDismissTimer) clearTimeout(existing.autoDismissTimer)
      existing.autoDismissTimer =
        duration === Infinity ? null : setTimeout(() => dismissToastById(existing.id), duration)
      updateToastById(existing.id, { ...props, count: nextCount })
      return {
        id: existing.id,
        dismiss: () => dismissToastById(existing.id),
        update: (u: ToasterToast) => updateToastById(existing.id, u),
      }
    }
    if (existing) dedupeState.delete(props.dedupeKey)
  }

  const id = Math.random().toString(36).slice(2, 9)

  // 挤压预警：若这次 ADD 后 state 长度超过 TOAST_LIMIT，最旧的 toast 会被 slice 掉，
  // 先清掉它的 dedupeState 条目，避免 orphan。
  if (memoryState.toasts.length >= TOAST_LIMIT) {
    const squeezed = memoryState.toasts[memoryState.toasts.length - 1]
    cleanDedupeEntry(squeezed.id)
  }

  if (props.dedupeKey) {
    dedupeState.set(props.dedupeKey, { id, count: 1, autoDismissTimer: null })
  }

  dispatch({
    type: actionTypes.ADD_TOAST,
    toast: {
      ...props,
      id,
      duration,
      count: props.dedupeKey ? 1 : props.count,
      open: true,
      onOpenChange: (open) => {
        if (!open) dismissToastById(id)
      },
    },
  })

  // Robust auto-dismiss. Radix's built-in close timer is suspended by its
  // pause-on-hover/focus state, and that pause state can get "stuck" (e.g.
  // when a toast is dismissed while the pointer is over it), leaving every
  // later toast stuck on screen forever. Scheduling the dismissal here
  // guarantees each toast closes after `duration` regardless of pointer/focus
  // state. DISMISS on an already-closed toast is a no-op, so this is safe.
  if (duration !== Infinity) {
    const timer = setTimeout(() => dismissToastById(id), duration)
    if (props.dedupeKey) {
      const entry = dedupeState.get(props.dedupeKey)
      if (entry && entry.id === id) {
        entry.autoDismissTimer = timer
      }
    }
  }

  return {
    id,
    dismiss: () => dismissToastById(id),
    update: (u: ToasterToast) => updateToastById(id, u),
  }
}

function useToast() {
  const [state, setState] = React.useState<State>(memoryState)

  React.useEffect(() => {
    listeners.add(setState)
    return () => {
      listeners.delete(setState)
    }
  }, [])

  return {
    ...state,
    toast,
    dismiss: (toastId?: string) => {
      dispatch({ type: actionTypes.DISMISS_TOAST, toastId })
      if (toastId) {
        addToRemoveQueue(toastId)
        cleanDedupeEntry(toastId)
      } else {
        state.toasts.forEach((toastItem) => {
          addToRemoveQueue(toastItem.id)
          cleanDedupeEntry(toastItem.id)
        })
      }
    },
  }
}

export { toast, useToast, DEDUPE_MAX_COUNT, TOAST_LIMIT }
