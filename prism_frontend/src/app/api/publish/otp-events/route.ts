import { NextResponse } from "next/server"

import { backendBaseUrl } from "@/lib/env"

/**
 * 待处理验证码事件代理。
 *
 * 后端真实端点：GET /api/v1/verification/otp-events
 * 返回 { success, data: { events: [...], total } }
 * 此处统一解包为 { events, total }，便于前端直接消费。
 */
export async function GET() {
  try {
    const response = await fetch(`${backendBaseUrl}/api/v1/verification/otp-events`, {
      cache: "no-store",
    })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) {
      return NextResponse.json({ events: [], total: 0, error: payload?.detail || "failed" }, {
        status: response.status,
      })
    }
    const data = payload?.data ?? payload
    return NextResponse.json(
      { events: data?.events ?? [], total: data?.total ?? 0 },
      { status: 200 }
    )
  } catch (error) {
    console.error("Failed to fetch otp events", error)
    return NextResponse.json({ code: 500, msg: "failed" }, { status: 500 })
  }
}
