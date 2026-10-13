"use client"

import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Clock3, Lock } from "lucide-react"

type DisabledField = {
  label: string
  placeholder: string
}

type PendingChannelCardProps = {
  title: string
  channel: string
  description: string
  fields: DisabledField[]
}

/**
 * "敬请期待"卡片：整个通道未接入，所有输入框 disabled。
 * 样式：opacity-60、cursor-not-allowed，标题右侧带灰底 Badge。
 */
export function PendingChannelCard({
  title,
  channel,
  description,
  fields,
}: PendingChannelCardProps) {
  return (
    <div className="rounded-2xl border border-border/70 bg-card opacity-60" aria-disabled="true">
      <div className="cursor-not-allowed space-y-1.5 p-5">
        <div className="flex flex-wrap items-center gap-2 text-foreground/70">
          <Lock className="h-4 w-4 text-muted-foreground" />
          <span className="text-base font-semibold leading-none tracking-tight">{title}</span>
          <span className="font-mono text-[11px] text-muted-foreground">{channel}</span>
          <Badge variant="outline" className="border-border/70 bg-card text-muted-foreground">
            <Clock3 className="mr-1 h-3 w-3" />
            敬请期待
          </Badge>
        </div>
        <p className="text-xs leading-5 text-muted-foreground">{description}</p>
      </div>
      <div className="space-y-4 p-5 pt-0 cursor-not-allowed">
        <div className="grid gap-3 md:grid-cols-2">
          {fields.map((field, idx) => (
            <div key={field.label} className="space-y-1.5">
              <label
                htmlFor={`${channel}-field-${idx}`}
                className="text-xs text-muted-foreground"
              >
                {field.label}
              </label>
              <Input
                id={`${channel}-field-${idx}`}
                disabled
                readOnly
                value=""
                placeholder={field.placeholder}
                onChange={() => {}}
                className="cursor-not-allowed border-border/70 bg-card/50 text-muted-foreground/60"
              />
            </div>
          ))}
        </div>
        <div className="rounded-xl border border-dashed border-border/70 bg-card/40 px-4 py-3 text-xs leading-5 text-muted-foreground">
          该通道功能待接入，请等待后续版本。
        </div>
      </div>
    </div>
  )
}
