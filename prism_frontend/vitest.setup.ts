/**
 * Vitest 全局 setup。
 *
 * 目前为空 —— 所有测试自己 `beforeEach` 里 stub 全局对象(fetch、URL 等),
 * 避免相互污染。保留此文件便于未来加通用 mock(如 localStorage 桩)。
 */

// 保持文件存在,避免 vitest.config 找不到入口。
export {}
