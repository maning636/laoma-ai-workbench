import type { NextConfig } from "next"

function normalizeBackendUrl(raw: string): string {
  const fallback = "http://127.0.0.1:7000"
  const trimmed = (raw || "").trim().replace(/\/+$/, "")
  const candidate = trimmed || fallback

  try {
    const url = new URL(candidate)
    if (url.hostname === "localhost") {
      url.hostname = "127.0.0.1"
    }
    return url.toString().replace(/\/+$/, "")
  } catch {
    return fallback
  }
}

const publicBackendUrl = normalizeBackendUrl(
  process.env.NEXT_PUBLIC_BACKEND_URL || process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:7000"
)

const internalBackendUrl = normalizeBackendUrl(
  process.env.LAOMA_INTERNAL_BACKEND_URL ||
    process.env.LAOMA_BACKEND_URL ||
    process.env.NEXT_PUBLIC_LAOMA_BACKEND_URL ||
    publicBackendUrl
)

function toRemotePattern(
  rawUrl: string
): { protocol: "http" | "https"; hostname: string; port?: string; pathname?: string } {
  const url = new URL(rawUrl)
  return {
    protocol: url.protocol.replace(":", "") as "http" | "https",
    hostname: url.hostname,
    ...(url.port ? { port: url.port } : {}),
  }
}

const backendPatterns = [publicBackendUrl, internalBackendUrl].map(toRemotePattern)

const localhostPatterns: Array<{ protocol: "http" | "https"; hostname: string; port?: string }> = [
  { protocol: "http", hostname: "localhost" },
  { protocol: "http", hostname: "127.0.0.1" },
  { protocol: "https", hostname: "localhost" },
  { protocol: "https", hostname: "127.0.0.1" },
]

const nextConfig: NextConfig = {
  // `output: "standalone"` is required by the desktop packaging pipeline
  // (desktop-electron copies `.next/standalone`), but Next 16.3 breaks on
  // Vercel when an adapter is injected (NEXT_ADAPTER_PATH) while standalone
  // output is enabled: the adapter build no longer emits
  // `.next/next-server.js.nft.json`, yet `copyTracedFiles` still reads it
  // unconditionally -> ENOENT in "Running onBuildComplete from Vercel".
  // See vercel/next.js#96646 (fixed upstream in canary only, #97287).
  // Vercel sets `VERCEL=1`; drop standalone there and keep it elsewhere.
  output: process.env.VERCEL ? undefined : "standalone",
  typescript: {
    // Skip type-checking during desktop packaging builds.
    ignoreBuildErrors: true,
  },
  turbopack: {
    root: __dirname,
  },
  webpack(config, { dev }) {
    if (
      !dev &&
      process.env.PRISM_DISABLE_CSS_MINIFY === "1" &&
      Array.isArray(config.optimization?.minimizer)
    ) {
      config.optimization.minimize = false
      config.optimization.minimizer = config.optimization.minimizer.filter((minimizer: unknown) => {
        const name = (minimizer as { constructor?: { name?: string } })?.constructor?.name
        return name !== "CssMinimizerPlugin"
      })
    }
    return config
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "api.dicebear.com",
      },
      {
        protocol: "https",
        hostname: "api.qrserver.com",
      },
      {
        protocol: "https",
        hostname: "images.unsplash.com",
      },
      {
        protocol: "https",
        hostname: "wx.qlogo.cn",
      },
      {
        protocol: "https",
        hostname: "res.wx.qq.com",
      },
      {
        protocol: "https",
        hostname: "p3-pc.douyinpic.com",
      },
      {
        protocol: "https",
        hostname: "p9-pc.douyinpic.com",
      },
      {
        protocol: "https",
        hostname: "p11.douyinpic.com",
      },
      {
        protocol: "https",
        hostname: "**.yximgs.com",
      },
      {
        protocol: "https",
        hostname: "**.xhscdn.com",
      },
      {
        protocol: "https",
        hostname: "i0.hdslb.com",
      },
      {
        protocol: "https",
        hostname: "i1.hdslb.com",
      },
      {
        protocol: "https",
        hostname: "i2.hdslb.com",
      },
      ...localhostPatterns,
      ...backendPatterns,
    ],
  },

  async rewrites() {
    const docsRewrites = [
      {
        source: "/docs",
        destination: `${internalBackendUrl}/apidocs/`,
      },
      {
        source: "/apidocs/:path*",
        destination: `${internalBackendUrl}/apidocs/:path*`,
      },
      {
        source: "/flasgger_static/:path*",
        destination: `${internalBackendUrl}/flasgger_static/:path*`,
      },
    ]

    const backendRewrites = [
      {
        source: "/api/chat",
        destination: `${internalBackendUrl}/api/v1/ai/chat`,
      },
      {
        source: "/api/v1/:path*",
        destination: `${internalBackendUrl}/api/v1/:path*`,
      },
      {
        source: "/api/:path*",
        destination: `${internalBackendUrl}/api/v1/:path*`,
      },
      {
        source: "/getFiles",
        destination: `${internalBackendUrl}/getFiles`,
      },
      {
        source: "/getValidAccounts",
        destination: `${internalBackendUrl}/getValidAccounts`,
      },
      {
        source: "/uploadSave",
        destination: `${internalBackendUrl}/uploadSave`,
      },
      {
        source: "/deleteFile",
        destination: `${internalBackendUrl}/deleteFile`,
      },
      {
        source: "/updateFileMeta",
        destination: `${internalBackendUrl}/updateFileMeta`,
      },
      {
        source: "/health",
        destination: `${internalBackendUrl}/health`,
      },
    ]

    return {
      beforeFiles: docsRewrites,
      afterFiles: [],
      fallback: backendRewrites,
    }
  },
}

// ─────────────────────────────────────────────────────────────────────────────
// 生产构建守卫:云端地址必须是真实域名,不能是本机地址
// ─────────────────────────────────────────────────────────────────────────────
// 背景:1.1.2 安装器曾把开发机的本地 cloud_service 地址(http://127.0.0.1:8091)
// 固化进浏览器 bundle,用户机器上那个端口根本不存在,云端登录/订阅必然失败。
// 这里让同类错误在 `next build` 阶段直接失败,而不是流到安装包里。
//
// 只在 phase-production-build 触发(next start 用 phase-production-server,
// 不会被误伤);确实要指向本机自建 cloud_service 时可用
// ALLOW_LOCALHOST_CLOUD_URL=1 放行。
const PHASE_PRODUCTION_BUILD = "phase-production-build"

function assertCloudUrlForProductionBuild(phase: string): void {
  if (phase !== PHASE_PRODUCTION_BUILD) return
  if (process.env.ALLOW_LOCALHOST_CLOUD_URL === "1") return

  const raw = (process.env.NEXT_PUBLIC_CLOUD_URL || "").trim()
  if (!raw) {
    throw new Error(
      "[next.config] 生产构建缺少 NEXT_PUBLIC_CLOUD_URL。" +
        "桌面端打包脚本(build-package.bat / build-community.ps1)会自动注入;" +
        "手动构建请显式设置云端根地址(不含 /cloud 后缀)。" +
        "确实要指向本机自建 cloud_service 时,设 ALLOW_LOCALHOST_CLOUD_URL=1 放行。",
    )
  }

  let hostname = ""
  try {
    hostname = new URL(raw).hostname
  } catch {
    throw new Error(`[next.config] NEXT_PUBLIC_CLOUD_URL 不是合法 URL: ${raw}`)
  }

  if (["localhost", "127.0.0.1", "0.0.0.0", "::1"].includes(hostname)) {
    throw new Error(
      `[next.config] 生产构建的 NEXT_PUBLIC_CLOUD_URL 指向本机(${hostname}),` +
        "会被固化进安装包。请改成云端域名(不含 /cloud 后缀);" +
        "确实要指向本机自建 cloud_service 时,设 ALLOW_LOCALHOST_CLOUD_URL=1 放行。",
    )
  }
}

export default function config(phase: string): NextConfig {
  assertCloudUrlForProductionBuild(phase)
  return nextConfig
}
