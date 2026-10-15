/**
 * F-E / F-F(F8) / F-G: 云网关高阶客户端。
 *
 * 目的:把后端 `CloudGateway` + `get_gateway()` 单例在前端镜像成
 * "面向业务语义"的高阶 API,补足:
 *   - `probeCloudReachable()`   后端 `probe_cloud_reachable` 的前端对偶
 *   - `buildTierContext()`      后端 `build_tier_context` 的前端对偶
 *   - `isUserAbort(err)`        F-G: 帮 chat 层把"用户主动中断"识别清楚,
 *                                避免被误判为失败而重试/回落
 *   - 常量 `USAGE_ESTIMATE_DISCLAIMER`   F-F(F11): 前端展示用的估算标注
 *
 * 分工(严格与既有模块解耦):
 *   - `client-gateway.ts`   只做"单发请求 / SSE 解析 / 错误归一化";
 *   - `cloud-auth.ts`       只做"token / 订阅状态";
 *   - **本文件**做"探测 / tier 决策 / 中断识别 / 常量"。
 *   - 本文件**不**修改 `client-gateway.ts`。
 *
 * F-F(F8) 关键点:
 *   `client-gateway.ts` 定义了 `CLOUD_FEATURES` 白名单({auth, subscription,
 *   license, usage, llm, billing}),但既有业务代码全都走 `feature: "cloud"`
 *   (显式云端 target),白名单分支从来没被真正用到。
 *   本文件走 feature 路由(例如 `feature: "usage"` 或 `feature: "license"`),
 *   让白名单分支真正生效,并配套测试证明。
 */

import {
  gatewayRequest,
  CLOUD_FEATURES,
  type GatewayRequestOptions,
  type GatewayErrorCode,
  type GatewayTarget,
} from "./client-gateway"

// ──────────────────────────────────────────────────────────────
// 常量 & 类型
// ──────────────────────────────────────────────────────────────

/**
 * 云端可达性探测的默认超时(毫秒)。
 *
 * 5s 是"能接受但不影响用户体感"的阈值:
 *   - 太短(1s) → 用户网络刚切换就误判为不可达,UI 抖动;
 *   - 太长(30s) → 阻塞渲染,尤其在 chat 前的 tier 决策会拖慢首屏。
 * 生产可按需覆盖(`probeCloudReachable({ timeoutMs: 2000 })`)。
 */
export const PROBE_CLOUD_TIMEOUT_MS = 5_000

/**
 * F-F(F11): 前端 usage 估算的相关常量与说明。
 *
 * 后端在流式上游不返回 `usage` 时,按 `len(text) // 2` 估算 token 数,
 * 中文场景可能偏 30% 以上(实际 1 汉字 ≈ 1 token,而 `//2` 会低估)。
 * 这个数字**只用于 UI 展示**,不做计费依据 —— 计费在后端 `_check_quota_and_consume`
 * 里按 `rp.cost` 硬编码,与前端展示无关。
 *
 * UI 层若要展示"已用 token",应:
 *   1. 直接展示后端返回的 `usage.prompt_tokens` / `completion_tokens`(权威);
 *   2. 无权威值时,展示 UI 估算并在文案里加"≈"或"估算"字样,避免误计费。
 */
export const USAGE_ESTIMATE_DISCLAIMER =
  "Estimated display-only; not used for billing. Use server-returned `usage` fields when available."

/** 前端的估算策略(仅供 UI 展示,不进入计费)。 */
export const USAGE_ESTIMATE = {
  /** 中文/多字节估算:1 字符 ≈ 0.5 token(与后端 `len//2` 对齐) */
  charsPerToken: 0.5,
  /** UI 建议标注:"估算" / "≈" */
  uiBadge: "≈",
}

/** Tier 上下文 —— 上层 prompt 路由 / UI 层用它决定走云端还是本地。 */
export interface TierContext {
  /** 建议走的目标 —— 云端可达且有 token 就 cloud,否则 local。 */
  tier: "cloud" | "local"
  /** 云端可达性探测结果(最近一次,可能滞后于真实网络)。 */
  cloudReachable: boolean
  /** 是否持有非空 access token(未登录为 false)。 */
  hasToken: boolean
  /** 若 cloud 不可达 / 无 token,给出简短原因,便于 UI 提示。 */
  reason?: string
}

// ──────────────────────────────────────────────────────────────
// F-E: probeCloudReachable
// ──────────────────────────────────────────────────────────────

export interface ProbeCloudReachableOptions {
  /** 探测超时(毫秒);默认 `PROBE_CLOUD_TIMEOUT_MS`。 */
  timeoutMs?: number
  /** 探测端点相对路径(默认 `llm/health`,轻量无 JWT)。 */
  path?: string
  /** 是否注入 token(默认 false —— 探测端点应允许匿名)。 */
  needToken?: boolean
  /** 覆盖 target(默认让 feature 白名单自动解析)。 */
  feature?: GatewayRequestOptions["feature"]
}

/**
 * 探测云端是否可达。
 *
 * 语义:
 *   - 走 `GET /cloud/llm/health`(默认,轻量、允许匿名);
 *   - 5s 超时(默认);超时 / 网络错 / 5xx 一律 false;
 *   - 4xx 也算 true(服务活着,只是拒绝未授权),
 *     这样"探测可达" ≠ "一定能用",UI 层还需自行判定 401/403。
 *   - **不抛异常**,永远返回 `boolean`。
 *
 * F-F(F8): 通过 `feature: "llm"` 走 `CLOUD_FEATURES` 白名单路由,
 * 而不是显式 `feature: "cloud"`,让白名单分支被真正使用到。
 */
export async function probeCloudReachable(
  opts: ProbeCloudReachableOptions = {},
): Promise<boolean> {
  const timeoutMs = opts.timeoutMs ?? PROBE_CLOUD_TIMEOUT_MS
  const path = opts.path ?? "llm/health"
  const feature = opts.feature ?? "llm" // 走 CLOUD_FEATURES 白名单
  const needToken = opts.needToken ?? false

  // 若 feature 不在白名单里,直接 fallback 到 "cloud" 显式路由
  // (不 fail —— 探测要"尽力而为",路由异常不应把用户挡在门外)
  const resolvedFeature = CLOUD_FEATURES.has(feature) ? feature : "cloud"

  try {
    const r = await gatewayRequest<{ status?: string }>({
      feature: resolvedFeature,
      path,
      method: "GET",
      needToken,
      timeoutMs,
    })
    // 2xx 明显可达;4xx(如 401)说明服务活着但拒绝 —— 也算"可达"。
    // 5xx 和 network 都算不可达。
    if (r.status === 0) return false
    if (r.code === "network") return false
    if (r.status >= 500) return false
    return true
  } catch {
    // gatewayRequest 内部已经吃掉了 fetch 异常,这里几乎不会跑到;
    // 但为了防御式编程,任何异常一律 false(不阻塞上层)。
    return false
  }
}

// ──────────────────────────────────────────────────────────────
// F-E: buildTierContext
// ──────────────────────────────────────────────────────────────

export interface BuildTierContextOptions {
  /** 是否真的发起网络探测。默认 true;false 时不探测,保守判 local。 */
  probe?: boolean
  /** 探测超时;透传给 probeCloudReachable。 */
  timeoutMs?: number
  /** 探测时是否需要 token。默认 false(走匿名 `/cloud/llm/health`)。 */
  probeNeedToken?: boolean
  /**
   * 覆盖 token 存在性判定。默认走 `client-gateway` 的 token provider。
   * 未注入 provider 且未提供此钩子时,`hasToken` 保守判为 false。
   */
  getToken?: () => Promise<string>
}

/**
 * 构造 tier 上下文,供 prompt 路由 / UI 决策"云端 vs 本地"使用。
 *
 * 规则:
 *   1. 无 token → `tier: "local"`, `reason: "no_token"`(不发探测请求,省流量)。
 *   2. 有 token + probe=true:
 *        - 云端可达 → `tier: "cloud"`
 *        - 云端不可达 → `tier: "local"`, `reason: "cloud_unreachable"`
 *   3. 有 token + probe=false → `tier: "local"`, `reason: "not_probed"`
 *
 * 后端对偶: `cloud_service/cloud_gateway.py::build_tier_context`
 */
export async function buildTierContext(
  opts: BuildTierContextOptions = {},
): Promise<TierContext> {
  const probe = opts.probe ?? true
  const probeNeedToken = opts.probeNeedToken ?? false

  // 拿 token —— 通过外部注入的 `getToken`;未注入时保守返回 false。
  // 这里刻意**不**动态 import cloud-auth,让本文件保持"纯 + 无副作用":
  //   - 无循环依赖(cloud-auth 只 import client-gateway,不 import 本文件);
  //   - 调用方明确注入 token 拉取能力,便于测试。
  const hasToken = opts.getToken ? await safeString(await opts.getToken()) : false

  if (!hasToken) {
    return { tier: "local", cloudReachable: false, hasToken: false, reason: "no_token" }
  }

  if (!probe) {
    return { tier: "local", cloudReachable: false, hasToken: true, reason: "not_probed" }
  }

  const reachable = await probeCloudReachable({
    timeoutMs: opts.timeoutMs,
    needToken: probeNeedToken,
  })
  if (!reachable) {
    return { tier: "local", cloudReachable: false, hasToken: true, reason: "cloud_unreachable" }
  }
  return { tier: "cloud", cloudReachable: true, hasToken: true }
}

function safeString(v: unknown): boolean {
  return typeof v === "string" && v.length > 0
}

// ──────────────────────────────────────────────────────────────
// F-G: isUserAbort
// ──────────────────────────────────────────────────────────────

/**
 * F-G: 判断一个错误/结果是否来自"用户主动中断"。
 *
 * 背景:客户端 AbortController / 断网都会让 fetch 抛 AbortError,
 * 但两种情况的语义完全不同:
 *   - **用户主动中断**(点击"停止生成"):内容已部分送达,用户已看到,
 *     不应该重试、不应回落到其他层;
 *   - **网络断线 / 超时**:是环境失败,可能应该重试/回落。
 *
 * 判定规则(与 client-gateway 的归一化对齐):
 *   1. `err.name === "AbortError"` 且 err.cause 缺失/不是 timeout → 用户中断;
 *   2. `err.detail === "aborted"`(gateway 层归一化后的结果) → 用户中断;
 *   3. `gateway code === "client"` + `detail === "aborted"` → 用户中断;
 *   4. AbortSignal 已被 aborted 且 abort reason 为 undefined/"aborted" → 用户中断。
 *
 * 用法:
 *   ```ts
 *   if (isUserAbort(err)) return // 不重试、不回落
 *   ```
 */
export function isUserAbort(
  err:
    | {
        name?: string
        cause?: unknown
        detail?: string
        message?: string
      }
    | null
    | undefined,
): boolean {
  if (!err) return false
  // 直接的 AbortError 对象
  if (err.name === "AbortError") {
    // 某些实现会带 cause 说明 timeout;此时不算"用户中断",算超时。
    const cause = err.cause
    if (cause && typeof cause === "object" && "name" in cause) {
      const causeName = (cause as { name?: string }).name
      if (causeName === "TimeoutError") return false
    }
    return true
  }
  // gateway 层归一化后的结果:detail 会显式标 "aborted"
  if (err.detail === "aborted") return true
  // fetch 抛的其他错误中,DOMException 有时不带 name(老浏览器),
  // 用 message 兜底一下 —— 仅匹配包含 "abort" 的字样。
  if (typeof err.message === "string") {
    const lower = err.message.toLowerCase()
    if (lower.includes("aborted") || lower.includes("abort")) return true
  }
  return false
}

/**
 * F-G: 判断 `AbortSignal` 是否已被"用户主动"abort(而非超时)。
 *
 * 用法:
 *   ```ts
 *   if (isUserAbortSignal(signal)) return { code: "aborted" }
 *   ```
 */
export function isUserAbortSignal(
  signal: AbortSignal | undefined | null,
): boolean {
  if (!signal || !signal.aborted) return false
  // 浏览器侧:signal.reason 为 undefined / "aborted" / DOMException(AbortError)
  // 都算用户中断。带 cause: TimeoutError 的按超时处理(不算用户中断)。
  const reason = signal.reason
  if (reason && typeof reason === "object") {
    const rName = (reason as { name?: string }).name
    if (rName === "TimeoutError") return false
  }
  return true
}

// ──────────────────────────────────────────────────────────────
// F-F(F8): 白名单路由的辅助
// ──────────────────────────────────────────────────────────────

/**
 * 判断一个 feature 名是否走云端。
 *
 * 复用 `CLOUD_FEATURES` 白名单(与后端 gateway 一致):
 *   { auth, subscription, license, usage, llm, billing } → cloud
 *   其他(如 "ping"、"files")                              → local
 * 显式 "cloud" / "local" 也接受。
 */
export function isCloudFeature(feature: string): GatewayTarget {
  const f = (feature || "").trim().toLowerCase()
  if (f === "cloud") return "cloud"
  if (f === "local") return "local"
  return CLOUD_FEATURES.has(f) ? "cloud" : "local"
}

/** 便捷:业务侧常用的 gatewayRequest 包装,显式走白名单 feature。 */
export async function cloudFeatureRequest<T>(
  feature: string,
  path: string,
  opts?: Omit<GatewayRequestOptions, "feature" | "path">,
): Promise<import("./client-gateway").GatewayResult<T>> {
  return gatewayRequest<T>({
    feature,
    path,
    ...opts,
  })
}

// ──────────────────────────────────────────────────────────────
// 便捷别名
// ──────────────────────────────────────────────────────────────

export const cloudGatewayClient = {
  probeCloudReachable,
  buildTierContext,
  isUserAbort,
  isUserAbortSignal,
  isCloudFeature,
  cloudFeatureRequest,
  USAGE_ESTIMATE_DISCLAIMER,
  USAGE_ESTIMATE,
  PROBE_CLOUD_TIMEOUT_MS,
}
