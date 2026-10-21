import { NextResponse } from "next/server"

import { backendBaseUrl } from "@/lib/env"

/**
 * 派发任务列表代理。
 *
 * 后端返回 {"status":"success","result":{"success":true,"items":[...]}}，
 * 前端消费方期望直接是数组，故在此解包为数组（与其它 list 代理保持一致）。
 */
export async function GET() {
  try {
    const res = await fetch(`${backendBaseUrl}/api/v1/tasks/distribution`, {
      // Ensure this runs server-side without caching stale task lists
      cache: "no-store",
    })

    if (!res.ok) {
      return NextResponse.json(
        { code: res.status, msg: "Failed to fetch tasks", data: [] },
        { status: res.status }
      )
    }

    const payload = await res.json().catch(() => ({}))
    const items = payload?.result?.items ?? payload?.items ?? []
    return NextResponse.json(items, { status: 200 })
  } catch (error) {
    console.error("distribution task proxy failed", error)
    return NextResponse.json({ code: 500, msg: "Proxy error", data: [] }, { status: 500 })
  }
}
