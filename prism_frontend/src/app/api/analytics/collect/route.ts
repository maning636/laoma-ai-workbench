import { NextRequest, NextResponse } from "next/server";

import { backendBaseUrl } from "@/lib/env";

/**
 * 后端只提供按平台的采集端点：POST /api/v1/analytics/collect/{platform}
 * （douyin / xiaohongshu / kuaishou / channels / bilibili）。
 * 本路由接收无 platform 的聚合请求，按平台逐个分发后再合并结果。
 */
const PLATFORM_ROUTE: Record<string, string> = {
  douyin: "douyin",
  tiktok: "douyin",
  xiaohongshu: "xiaohongshu",
  redbook: "xiaohongshu",
  xhs: "xiaohongshu",
  kuaishou: "kuaishou",
  channels: "channels",
  tencent: "channels",
  bilibili: "bilibili",
};

export async function POST(request: NextRequest) {
  try {
    const incoming = await request.json().catch(() => ({}));
    const account_ids: string[] | undefined = incoming?.account_ids;
    const requested = incoming?.platform
      ? [String(incoming.platform).toLowerCase()]
      : Object.keys(PLATFORM_ROUTE);

    // 去重并保持顺序
    const targets = Array.from(new Set(requested.map((p) => PLATFORM_ROUTE[p]).filter(Boolean)));

    if (!targets.length) {
      return NextResponse.json(
        { success: false, error: `不支持的平台: ${incoming?.platform}` },
        { status: 400 }
      );
    }

    const results: Record<string, any> = {};
    const errors: Record<string, string> = {};
    let success = true;

    for (const platform of targets) {
      try {
        const response = await fetch(`${backendBaseUrl}/api/v1/analytics/collect/${platform}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(account_ids ? { account_ids } : {}),
        });
        const backend = await response.json().catch(() => ({}));
        if (!response.ok) {
          success = false;
          errors[platform] = backend?.detail || backend?.error || `HTTP ${response.status}`;
          continue;
        }
        results[platform] = backend?.data ?? backend;
      } catch (error) {
        success = false;
        errors[platform] = String(error);
      }
    }

    return NextResponse.json(
      {
        success,
        data: results,
        errors,
        message: success
          ? `已采集: ${Object.keys(results).join(", ")}`
          : `部分平台采集失败: ${Object.keys(errors).join(", ")}`,
      },
      { status: success ? 200 : 207 }
    );
  } catch (error) {
    console.error("Analytics collect error:", error);
    return NextResponse.json(
      { success: false, error: String(error) },
      { status: 500 }
    );
  }
}
