import { NextRequest } from "next/server"

import { backendBaseUrl } from "@/lib/env"

// =============================================================
// Hermes SSE 流式代理
// ------------------------------------------------------------
// 后端 POST /api/v1/agent/hermes-stream 返回 text/event-stream。
//
// 为什么需要这一层而不是直接吃 next.config.ts 的 fallback rewrite：
// fallback rewrite 走的是 Next 的通用代理，会把上游响应整体缓冲后再吐给
// 浏览器，SSE 的心跳/增量事件因此全部卡在服务端——浏览器侧表现为
// “正在连接 Hermes Agent…” 永远不出结果，Network 面板里请求一直是 pending。
//
// Route Handler 直接把上游 ReadableStream 透传，事件可以边到边渲染。
// 同源转发顺带绕开了跨域问题（后端 CORS 不必放行前端 origin）。
// =============================================================

export const runtime = "nodejs"
export const dynamic = "force-dynamic"
// Hermes 一轮执行可能跑很久，别让平台层提前掐断。
export const maxDuration = 300

export async function POST(req: NextRequest) {
  let body: string
  try {
    body = await req.text()
  } catch {
    return new Response(JSON.stringify({ detail: "request body unreadable" }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    })
  }

  let upstream: Response
  try {
    upstream = await fetch(`${backendBaseUrl}/api/v1/agent/hermes-stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
      cache: "no-store",
    })
  } catch (e) {
    return new Response(
      JSON.stringify({ detail: `后端不可达：${e instanceof Error ? e.message : String(e)}` }),
      { status: 502, headers: { "Content-Type": "application/json" } }
    )
  }

  if (!upstream.ok || !upstream.body) {
    const text = await upstream.text().catch(() => "")
    return new Response(text || JSON.stringify({ detail: `HTTP ${upstream.status}` }), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") || "application/json" },
    })
  }

  // 直接透传上游流，保留 SSE 分帧。
  return new Response(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  })
}
