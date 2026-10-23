/**
 * 云端 LLM 可用性探测(P7:云端 AI 未配置时关掉入口)。
 *
 * 背景:
 *   服务端没有配 `CLOUD_LLM_API_KEY` 时,`/cloud/llm/chat` 与 `/cloud/llm/stream`
 *   都会失败。客户端与其让用户点进去吃一个 503,不如**先探一下再决定要不要露入口**。
 *
 * 三态语义(这是本模块最要紧的地方):
 *
 *   - `available`   —— 服务端明确回「key 已配置」。正常显示云端入口。
 *   - `unavailable` —— 服务端明确回「key 未配置」。**这时才隐藏入口**。
 *   - `unknown`     —— 探测本身没拿到结论(网络抖动 / 超时 / 5xx / 响应形状不认识)。
 *                      此时**保持现状**(入口照旧显示),绝不能因为一次抖动就把
 *                      正常用户的云端入口误伤掉。
 *
 * 换句话说:`unknown ≠ unavailable`。把两者混为一谈是这类"自动隐藏入口"最常见的
 * 线上事故来源 —— 用户网络抖一下,云端 AI 入口就消失了,而且再也回不来。
 *
 * 数据来源:
 *   `GET /cloud/llm/health`(匿名可访问的运维探针),返回形如:
 *     `{ api_key_configured: boolean, available: boolean, message: string, ... }`
 *   `available` 字段是服务端侧新增的机器可读开关;为兼容更老的部署,
 *   也接受只回 `api_key_configured` 的形状。
 *
 * 依赖:client-gateway(走 `feature: "llm"` 白名单路由 → 云端)
 */

import { gatewayRequest } from "./client-gateway"

// ──────────────────────────────────────────────────────────────
// 类型
// ──────────────────────────────────────────────────────────────

/**
 * 云端 LLM 的可用性三态。
 *
 * - `available`   : 服务端确认已配置
 * - `unavailable` : 服务端确认未配置(客户端据此隐藏入口)
 * - `unknown`     : 探测未得出结论(客户端保持现状)
 */
export type CloudLlmAvailability = "available" | "unavailable" | "unknown"

export interface CloudLlmAvailabilityResult {
  availability: CloudLlmAvailability
  /** 服务端返回的中文说明(若有)。用于在 UI 上给一句人话。 */
  message?: string
  /** 探测失败时的原因,便于排查。 */
  reason?: string
}

/** 探测超时(毫秒)。5s 与既有 `probeCloudReachable` 保持一致。 */
export const CLOUD_LLM_PROBE_TIMEOUT_MS = 5_000

/** 后端 `/cloud/llm/health` 的响应形状(只声明我们用到的字段)。 */
interface HealthPayload {
  api_key_configured?: unknown
  available?: unknown
  message?: unknown
}

// ──────────────────────────────────────────────────────────────
// 核心探测
// ──────────────────────────────────────────────────────────────

/**
 * 从 health 响应里判定可用性。
 *
 * 判定顺序(先看机器可读的 `available`,再看 `api_key_configured`):
 *   - 字段缺失 / 类型不对 → `unknown`(不认识就是不认识,别猜)
 *   - 布尔值 → 直接采纳
 *
 * 导出是为了单测:把"响应 → 结论"这一步单独测透,不依赖网络。
 */
export function resolveCloudLlmAvailability(
  payload: unknown,
): CloudLlmAvailabilityResult {
  if (!payload || typeof payload !== "object") {
    return { availability: "unknown", reason: "invalid_payload" }
  }
  const body = payload as HealthPayload

  const rawAvailable = body.available
  const rawConfigured = body.api_key_configured

  let configured: boolean | undefined
  if (typeof rawAvailable === "boolean") {
    configured = rawAvailable
  } else if (typeof rawConfigured === "boolean") {
    configured = rawConfigured
  }

  if (configured === undefined) {
    // 服务端回了一个我们不认识的形状(旧版本部署 / 代理返回了别的东西)。
    // 判 unknown —— 保持现状,而不是当成"未配置"去隐藏入口。
    return { availability: "unknown", reason: "unrecognized_payload" }
  }

  const message = typeof body.message === "string" ? body.message : undefined

  return configured
    ? { availability: "available", message }
    : { availability: "unavailable", message }
}

/**
 * 探测云端 LLM 是否已配置。
 *
 * 永不抛异常:任何失败都归入 `unknown`。
 *
 * @param opts.timeoutMs 探测超时;默认 `CLOUD_LLM_PROBE_TIMEOUT_MS`
 */
export async function probeCloudLlmAvailability(
  opts: { timeoutMs?: number } = {},
): Promise<CloudLlmAvailabilityResult> {
  const timeoutMs = opts.timeoutMs ?? CLOUD_LLM_PROBE_TIMEOUT_MS

  try {
    const resp = await gatewayRequest<HealthPayload>({
      feature: "llm",
      path: "llm/health",
      method: "GET",
      // health 端点允许匿名;不注入 token,免得探测依赖登录态。
      needToken: false,
      timeoutMs,
    })

    if (!resp.ok) {
      // 网络不可达 / 5xx / 超时 —— 拿不到结论,判 unknown。
      return {
        availability: "unknown",
        reason: `probe_failed:${resp.code ?? "unknown"}`,
        message: resp.detail,
      }
    }

    return resolveCloudLlmAvailability(resp.data)
  } catch (e: unknown) {
    return {
      availability: "unknown",
      reason: "probe_exception",
      message: e instanceof Error ? e.message : String(e),
    }
  }
}

// ──────────────────────────────────────────────────────────────
// 判定辅助
// ──────────────────────────────────────────────────────────────

/**
 * 是否应该隐藏云端 AI 入口。
 *
 * **只有明确 `unavailable` 才隐藏。**`unknown` 一律返回 false(保持现状)。
 */
export function shouldHideCloudLlmEntry(
  availability: CloudLlmAvailability | null | undefined,
): boolean {
  return availability === "unavailable"
}

/**
 * 给用户看的一句中文说明。
 *
 * - `unavailable`:用服务端给的中文说明(信息最准)
 * - `unknown`     :说明"探测失败,按本地可用处理",而不是说"没配"
 */
export function describeCloudLlmAvailability(
  availability: CloudLlmAvailability,
  message?: string,
): string {
  if (availability === "available") {
    return message || "云端 AI 已配置,可正常使用。"
  }
  if (availability === "unavailable") {
    return (
      message ||
      "云端 AI 未配置:服务端未设置 CLOUD_LLM_API_KEY,云端对话与云端高级 Prompt 暂不可用。" +
        "请改用本地模型(Settings → AI 服务商配置),或联系管理员开通云端 AI。"
    )
  }
  return message || "云端 AI 状态未知(探测失败),已按本地模式处理。"
}
