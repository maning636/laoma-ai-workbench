import { defineConfig } from "vitest/config"
import { fileURLToPath } from "node:url"

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url))

export default defineConfig({
  test: {
    // client-gateway 只用 fetch / AbortController / URL / TextDecoder,
    // 都是 Node 18+ 原生能力,走 node 环境足够;避免装 jsdom 引入额外依赖。
    environment: "node",
    include: ["src/**/__tests__/**/*.test.{ts,tsx}", "src/**/*.test.{ts,tsx}"],
    // 保留 setupFiles 入口,便于未来加通用 mock(如 localStorage 桩)。
    setupFiles: ["./vitest.setup.ts"],
  },
  resolve: {
    alias: {
      "@": r("./src"),
    },
  },
})
