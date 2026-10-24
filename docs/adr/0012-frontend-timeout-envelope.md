# ADR-0012: 前端请求层统一 30s 超时 + envelope 兼容层

- **状态**：已接受（补录）
- **日期**：2026-10-24
- **决策者**：工作组
- **证据分级**：【已验证】

---

## 背景

2026-10-24 收官冲刺中，前端请求层暴露两个问题：

1. **超时误报 500**：某些长耗时 API（LLM 对话、批量发布、视频分析）超过默认 30s 后被浏览器/fetch 报 500，实际后端仍在处理。用户看到「服务器错误」但实际是「超时」。
2. **裸 fetch 散落**：`prism_frontend/src/` 里存在多处直接 `fetch()` 调用（未走封装），不享受统一超时、错误处理、retry 逻辑。

**证据**：
- `git show --stat 2c547c7`：feat(ux): 应用感修复——请求超时/loading骨架/重组件懒加载/isLoading/导航预取
- `git show --stat 16ca1d6`：fix(ux): 超时误报 500 修正为 408 语义 + 三处裸 fetch 接入超时封装

## 决策

**前端请求层统一 30s 超时 + envelope 兼容层**：

1. 所有 `fetch` 调用走统一封装，默认 30s 超时
2. 超时返回 **408 Gateway Timeout**（而非 500）语义
3. 后端返回统一 envelope 结构：`{ code, message, data, trace_id }`
4. 兼容旧后端返回：非 envelope 结构自动包装成 `{ code: 0, message: "ok", data: <original>, trace_id: null }`

**具体落地**：
- `2c547c7`：feat(ux): 应用感修复——请求超时/loading骨架/重组件懒加载/isLoading/导航预取
- `16ca1d6`：fix(ux): 超时误报 500 修正为 408 语义 + 三处裸 fetch 接入超时封装
- `prism_frontend/src/lib/http.ts`（或类似路径）：统一请求层
- `prism_frontend/src/components/*/`：清理裸 fetch 调用

**envelope 兼容层**：
- 响应体检测：`typeof body === 'object' && body !== null && 'code' in body && 'data' in body`
- 命中 envelope：直接用
- 未命中：包装成 envelope（`code: 0` 表成功）

## 否掉了什么

| 方案 | 为什么否 |
|---|---|
| 每个请求手动设超时 | 遗漏率高，且超时阈值不一致 |
| 后端负责超时控制 | 前端也需要感知超时，否则 UI 卡在 loading 态 |
| 用 500 语义表示超时 | 用户误解为服务器错误，触发误投诉（`16ca1d6` 修复） |
| 后端全量改成 envelope（强制迁移） | 破坏向后兼容；旧客户端不识别新结构 |
| 后端返回裸 JSON + 前端各自解析 | 错误处理不一致，用户体验混乱 |
| 超时时间设 60s+ | 用户感知等待时间过长，且占用浏览器连接 |

## 代价

**收益**：
- 前端错误处理统一，超时语义清晰（408 而非 500）
- 用户看到「请求超时」而非「服务器错误」，减少误投诉
- 新后端接口可以渐进式接入 envelope，无需一次性迁移

**代价**：
- 前后端字段契约需严格对齐（envelope 检测逻辑）
- 兼容层增加 1 层判断（性能开销可忽略）
- 旧后端接口需按业务优先级渐进式改造

**已知副作用**：
- 部分旧后端返回 `null` 或 `undefined`，envelope 检测需防御
- 前端 loading 态与超时态的 UX 需单独设计（`2c547c7` 已加 loading 骨架）

## 未来复审触发条件

- 长耗时 API 增多（LLM 流式对话、批量任务），需评估是否支持 SSE / WebSocket
- 后端全量迁移到 envelope 后，兼容层可下线
- 超时时间需按 API 类型分级（如 LLM 对话 60s、列表查询 10s）

## 参考

- `git show --stat 2c547c7` `16ca1d6`
- `prism_frontend/src/lib/http.ts`（或项目内实际请求层路径）
