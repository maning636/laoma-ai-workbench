function normalizeBackendBaseUrl(raw: string): string {
  const trimmed = (raw || "").trim().replace(/\/+$/, "")
  const normalized = (trimmed || "http://127.0.0.1:7000").replace(/\/api\/v1$/i, "")

  try {
    const url = new URL(normalized)
    if (url.hostname === "localhost") {
      url.hostname = "127.0.0.1"
    }
    return url.toString().replace(/\/+$/, "")
  } catch {
    return normalized
  }
}

export const backendBaseUrl = normalizeBackendBaseUrl(
  // 服务端（Next.js route handler）优先用容器内可达的后端地址（如 http://app:7000）。
  // 该变量不带 NEXT_PUBLIC_ 前缀，不会被注入浏览器端 bundle，客户端会回落到 NEXT_PUBLIC_BACKEND_URL。
  process.env.LAOMA_INTERNAL_BACKEND_URL ??
    process.env.NEXT_PUBLIC_BACKEND_URL ??
    process.env.NEXT_PUBLIC_API_BASE ??
    "http://127.0.0.1:7000"
)

/**
 * C16:云端 SaaS 后端地址(与 `backendBaseUrl` 平行的第二个 base URL)。
 *
 * 只承载认证 / 订阅 / 云端 LLM / license 校验相关请求;
 * 浏览器自动化、文件、账号同步、发布等本地功能仍走 `backendBaseUrl`。
 *
 * 优先级:
 *   1. NEXT_PUBLIC_CLOUD_URL   浏览器端显式配置
 *   2. LAOMA_CLOUD_BASE_URL    后端构建期注入(可选)
 *   3. 默认 https://api.prism.local/cloud
 *
 * 若用户填写的是根域名(不带 /cloud),自动补上,便于部署时省略路径。
 */
function normalizeCloudBaseUrl(raw: string | undefined): string {
  const trimmed = (raw || "").trim().replace(/\/+$/, "")
  if (!trimmed) return "https://api.prism.local"
  // 与 cloud_service 约定:根 URL 不含 /cloud 后缀,由下方 API_ENDPOINTS 统一加前缀。
  // 若用户填了 `.../cloud`,去掉以避免端点重复拼出 `/cloud/cloud/...`。
  if (/\/cloud$/i.test(trimmed)) return trimmed.replace(/\/cloud$/i, "")
  return trimmed
}

export const cloudBaseUrl = normalizeCloudBaseUrl(
  process.env.NEXT_PUBLIC_CLOUD_URL ?? process.env.LAOMA_CLOUD_BASE_URL
)

export const API_ENDPOINTS = {
  base: backendBaseUrl,

  getFiles: `${backendBaseUrl}/api/v1/files`,
  uploadFile: `${backendBaseUrl}/api/v1/files/upload`,
  uploadSave: `${backendBaseUrl}/api/v1/files/upload-save`,
  deleteFile: (fileId: number) => `${backendBaseUrl}/api/v1/files/${fileId}`,
  updateFileMeta: (fileId: number) => `${backendBaseUrl}/api/v1/files/${fileId}`,
  getFile: (fileId: number) => `${backendBaseUrl}/api/v1/files/${fileId}`,
  fileStats: `${backendBaseUrl}/api/v1/files/stats/summary`,

  getValidAccounts: `${backendBaseUrl}/api/v1/accounts`,
  deleteAccount: (accountId: string) => `${backendBaseUrl}/api/v1/accounts/${accountId}`,
  updateUserinfo: (accountId: string) => `${backendBaseUrl}/api/v1/accounts/${accountId}`,
  verifyAccount: (accountId: string) => `${backendBaseUrl}/api/v1/accounts/${accountId}/verify`,
  batchVerify: `${backendBaseUrl}/api/v1/accounts/batch-verify`,
  deepSync: `${backendBaseUrl}/api/v1/accounts/deep-sync`,
  accountStats: `${backendBaseUrl}/api/v1/accounts/stats/summary`,

  postVideo: `${backendBaseUrl}/api/v1/publish`,
  postVideoBatch: `${backendBaseUrl}/api/v1/publish/batch`,

  aiChat: `${backendBaseUrl}/api/v1/ai/chat`,
  aiProviders: `${backendBaseUrl}/api/v1/ai/providers`,
  aiModels: `${backendBaseUrl}/api/v1/ai/models`,
  aiHealth: `${backendBaseUrl}/api/v1/ai/health`,
  aiModelConfigs: `${backendBaseUrl}/api/v1/ai/model-configs`,
  aiTestConnection: `${backendBaseUrl}/api/v1/ai/test-connection`,

  agentContext: `${backendBaseUrl}/api/v1/agent/context`,
  agentSaveScript: `${backendBaseUrl}/api/v1/agent/save-script`,
  agentExecuteScript: `${backendBaseUrl}/api/v1/agent/execute-script`,
  agentScripts: `${backendBaseUrl}/api/v1/agent/scripts`,
  agentExecutions: `${backendBaseUrl}/api/v1/agent/executions`,
  agentOpenClawRun: `${backendBaseUrl}/api/v1/agent/openclaw-run`,
  agentHermesRun: `${backendBaseUrl}/api/v1/agent/hermes-run`,

  AI_PROMPTS: `${backendBaseUrl}/api/v1/ai-prompts`,

  health: `${backendBaseUrl}/health`,
  ping: `${backendBaseUrl}/api/v1/ping`,

  // ── C16 云端 SaaS 端点(全部走 cloudBaseUrl)──
  // 认证 / 订阅 / 云端 LLM / license 校验
  cloudAuthRegister: `${cloudBaseUrl}/cloud/auth/register`,
  cloudAuthLogin: `${cloudBaseUrl}/cloud/auth/login`,
  cloudAuthRefresh: `${cloudBaseUrl}/cloud/auth/refresh`,
  cloudAuthMe: `${cloudBaseUrl}/cloud/auth/me`,
  cloudSubscription: `${cloudBaseUrl}/cloud/subscription`,
  cloudLicenseVerify: `${cloudBaseUrl}/cloud/license/verify`,
  cloudLlmChat: `${cloudBaseUrl}/cloud/llm/chat`,
  cloudLlmPrompts: `${cloudBaseUrl}/cloud/llm/prompts`,
  cloudLlmHealth: `${cloudBaseUrl}/cloud/llm/health`,
}

export const PLATFORM_CODES = {
  XIAOHONGSHU: 1,
  TENCENT: 2,
  DOUYIN: 3,
  KUAISHOU: 4,
  BILIBILI: 5,
} as const

export const PLATFORM_NAMES = {
  [PLATFORM_CODES.XIAOHONGSHU]: "小红书",
  [PLATFORM_CODES.TENCENT]: "视频号",
  [PLATFORM_CODES.DOUYIN]: "抖音",
  [PLATFORM_CODES.KUAISHOU]: "快手",
  [PLATFORM_CODES.BILIBILI]: "B 站",
} as const
