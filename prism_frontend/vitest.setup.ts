/**
 * Vitest 全局 setup。
 *
 * 目前为空 —— 所有测试自己 `beforeEach` 里 stub 全局对象(fetch、URL 等),
 * 避免相互污染。保留此文件便于未来加通用 mock(如 localStorage 桩)。
 *
 * DOM 交互测试（@testing-library/jest-dom）：在此加载 jest-dom matcher
 * 扩展 `expect`。对纯逻辑测试（node 环境）无副作用，只在真正做
 * DOM 断言的测试里生效。
 */
import "@testing-library/jest-dom/vitest"

// 保持文件存在,避免 vitest.config 找不到入口。
export {}
