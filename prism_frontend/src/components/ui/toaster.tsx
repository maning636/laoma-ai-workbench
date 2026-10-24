"use client"

import * as React from "react"

import { useToast } from "@/components/ui/use-toast"
import {
  Toast,
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "@/components/ui/toast"

export type ToastProps = React.ComponentPropsWithoutRef<typeof Toast>
export type ToastActionElement = React.ReactElement<typeof ToastClose>

export function Toaster() {
  const { toasts } = useToast()

  return (
    <ToastProvider>
      {toasts.map(function ({ id, title, description, action, dedupeKey, count, ...props }) {
        void dedupeKey // 仅用于 use-toast 内部去重，不进 DOM
        const showCount = typeof count === "number" && count > 1
        return (
          <Toast key={id} {...props}>
            <div className="grid gap-1">
              {title ? (
                <div className="flex items-center gap-2">
                  <ToastTitle>{title}</ToastTitle>
                  {showCount ? (
                    <span
                      aria-label={`已出现 ${count} 次`}
                      className="inline-flex min-w-[20px] items-center justify-center rounded-full border border-border bg-foreground/10 px-1.5 py-0.5 text-[10px] font-medium leading-none"
                    >
                      ×{count}
                    </span>
                  ) : null}
                </div>
              ) : null}
              {description && <ToastDescription>{description}</ToastDescription>}
            </div>
            {action}
            <ToastClose />
          </Toast>
        )
      })}
      <ToastViewport />
    </ToastProvider>
  )
}
