/**
 * TikHub 数据接口可用性探测(P7:未配置时关掉必然失败的入口)。
 *
 * 与 `cloud-llm-availability.ts` 同构的三态语义:
 *
 *   - `available`   —— 后端 `/api/v1/tikhub/health` 明确回 `tikhub_enabled: true`
 *   - `unavailable` —— 明确回 `false`(没配 key)→ 客户端隐藏依赖 TikHub 的入口
 *   - `unknown`     —— 探测失败 / 形状不认识 → **保持现状**,不误伤
 *
 * 注意与云端 LLM 的区别:
 *   TikHub 的 key 是**用户自己在设置页填的**(存 `ai_model_configs`),
 *   不是平台统一发的。所以"未配置"是常态而非故障 —— 这时客户端只是
 *   不该给出"点了必然失败"的按钮,而不是要报错。
 *
 * 依赖:走本地后端(不是云端),因此用 backendBaseUrl 直接 fetch。
 */

import { backendBaseUrl } from "./env"

export type TikHubAvailability = "available" | "unavailable" | "unknown"

export interface TikHubAvailabilityResult {
  availability: TikHubAvailability
  /** 后端返回的中文说明(若有)。 */
  message?: string
  /** 探测失败原因,便于排查。 */
  reason?: string
}

/** 探测超时(毫秒)。 */
export const TIKHUB_PROBE_TIMEOUT_MS = 5_000

interface TikHubHealthPayload {
  configured?: unknown
  tikhub_enabled?: unknown
  message?: unknown
}

/**
 * 从 health 响应里判定可用性(导出以便单测,不必依赖网络)。
 */
export function resolveTikHubAvailability(
  payload: unknown,
): TikHubAvailabilityResult {
  if (!payload || typeof payload !== "object") {
    return { availability: "unknown", reason: "invalid_payload" }
  }
  const body = payload as TikHubHealthPayload

  let configured: boolean | undefined
  if (typeof body.tikhub_enabled === "boolean") {
    configured = body.tikhub_enabled
  } else if (typeof body.configured === "boolean") {
    configured = body.configured
  }

  if (configured === undefined) {
    return { availability: "unknown", reason: "unrecognized_payload" }
  }

  const message = typeof body.message === "string" ? body.message : undefined
  return configured
    ? { availability: "available", message }
    : { availability: "unavailable", message }
}

/**
 * 探测 TikHub 是否已配置。永不抛异常。
 */
export async function probeTikHubAvailability(
  opts: { timeoutMs?: number } = {},
): Promise<TikHubAvailabilityResult> {
  const timeoutMs = opts.timeoutMs ?? TIKHUB_PROBE_TIMEOUT_MS
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const resp = await fetch(`${backendBaseUrl}/api/v1/tikhub/health`, {
      method: "GET",
      cache: "no-store",
      signal: controller.signal,
    })
    if (!resp.ok) {
      return { availability: "unknown", reason: `probe_http_${resp.status}` }
    }
    const payload = await resp.json().catch(() => null)
    return resolveTikHubAvailability(payload)
  } catch (e: unknown) {
    return {
      availability: "unknown",
      reason: "probe_exception",
      message: e instanceof Error ? e.message : String(e),
    }
  } finally {
    clearTimeout(timer)
  }
}

/**
 * 是否应该隐藏依赖 TikHub 的入口。
 *
 * **只有明确 `unavailable` 才隐藏。**`unknown` 一律返回 false。
 */
export function shouldHideTikHubEntry(
  availability: TikHubAvailability | null | undefined,
): boolean {
  return availability === "unavailable"
}

/** 给用户看的一句中文说明。 */
export function describeTikHubAvailability(
  availability: TikHubAvailability,
  message?: string,
): string {
  if (availability === "available") {
    return message || "TikHub 数据接口已配置。"
  }
  if (availability === "unavailable") {
    return (
      message ||
      "TikHub 数据接口未配置:快手 / 小红书 / 视频号采集走浏览器方式;" +
        "TikTok / YouTube 反查补全需要 TikHub,请在 Settings → 数据采集接口 中配置 API Key。"
    )
  }
  return message || "TikHub 配置状态未知(探测失败)。"
}
