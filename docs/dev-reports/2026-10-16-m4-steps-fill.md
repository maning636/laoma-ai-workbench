# M4 场景引导 Wizard · 步骤骨架填充报告

- 报告日期：2026-10-20
- 模块负责人：M4 前端子代理
- 前置阅读：
  - `docs/dev-reports/2026-10-16-m4-implementation.md`（M4 骨架版）
  - `docs/dev-reports/2026-10-16-m1-frontend.md`（M1 AI 生图工作台）
- 验证：`npx tsc --noEmit` 0 error；`npm test` **297/297 PASS**（新增 15 用例，原 282 保持通过）

---

## 1. 实现文件清单

### 新增

| 路径 | 行数 | 职责 |
|---|---:|---|
| `prism_frontend/src/components/wizard/wizard-state-cache.ts` | ~150 | 跨步骤 draft 缓存（`getSceneDraft/setSceneDraft/clearSceneDraft`）+ AgentPickerStep 事件订阅 |
| `prism_frontend/src/components/wizard/__tests__/wizard-state-cache.test.ts` | ~100 | 6 用例：缓存读写/清理/隔离/默认值 |

### 修改

| 路径 | 变更 |
|---|---|
| `prism_frontend/src/components/wizard/scenarios.tsx` | 骨架 → 实际功能：4 个场景 × 13 步全部接入；`PUBLISH_PLATFORMS` 扩到 8 平台；新增 `mockAiSuggestTopics` / `mockAiGenerateContent` / `mockAiGenerateImages` |
| `prism_frontend/src/components/wizard/scenario-guide.tsx` | `ScenarioWizardBlock` 卸载时 `resetScenarioDraft`，避免下次进入残留 |
| `prism_frontend/src/components/wizard/index.ts` | Barrel 出口新增 mock 函数、draft 类型、cache API |
| `prism_frontend/src/components/wizard/__tests__/scenarios.test.tsx` | 15 → 24 用例（新增 8 平台断言 + 3 mock 函数行为） |

### 未修改

- 未新增依赖（复用 shadcn `Button/Textarea` + `lucide-react` + 项目自有 `image-studio.ts`）
- 未改动 M1/M2/M3/M5 任何代码
- 未改 `wizard-core.ts` / `wizard.tsx` / `url-sync.ts` / `agent-picker-step.tsx`

---

## 2. 各场景步骤实现

### 2.1 场景1 · AI 写稿发布（4 步）

| # | 步骤 | 实现 |
|---|---|---|
| 1 | 选择目标平台 | `PUBLISH_PLATFORMS` × 8（抖音/快手/B 站/小红书/视频号/知乎/头条/西瓜），`ToggleCard` 多选卡片；选中列表写入 `AiWritingDraft.platformIds` |
| 2 | 选题 | `Textarea` 输入选题；`Sparkles` 按钮调 `mockAiSuggestTopics()` 返回 3 条候选，点击填充选题框；写 `AiWritingDraft.topic` |
| 3 | AI 生成内容 | `Wand2` 按钮 → 400ms mock 延迟 → `mockAiGenerateContent()` 返回 3 条标题候选 + 5 个标签 + 可编辑正文；点选标题、编辑正文都写入 draft |
| 4 | 确认并发布 | 预览上一步生成的标题/标签/正文 + 目标平台；`Send` 按钮 700ms mock 发布 → 显示 "Mock 发布成功" |

### 2.2 场景2 · AI 生图（5 步）

| # | 步骤 | 实现 |
|---|---|---|
| 1 | 上传原图 | 原生 `<input type="file">` + `FileReader.readAsDataURL` 本地预览；`isAcceptedImage`（M1）过滤 MIME；最多 7 张；写 `AiImageDraft.referencePreview[]` |
| 2 | 智能体选择 | 复用 M2 已完成的 `AgentPickerStep`（M2 hardening 后含 JWT + Pro 配额判断） |
| 3 | 选择图片类型 | 4 种类型（`IMAGE_TYPES` 来自 `lib/image-studio.ts`：封面/配图/海报/白底），`ToggleCard` 单选；写 `AiImageDraft.imageTypeId` |
| 4 | 生成 | `Wand2` 按钮 → 900ms mock 延迟 → `mockAiGenerateImages()` 返回 4 张 `picsum.photos/seed/…/512/512.jpg`；每张有 "编辑" 按钮跳 `/tools/image-editor?url=…` |
| 5 | 编辑 / 发布 | 图片网格，每张提供"编辑"按钮（`buildEditorUrl` 跳转 M5） |

### 2.3 场景3 · 视频流水线（3 步）

| # | 步骤 | 实现 |
|---|---|---|
| 1 | 选择素材 | `<input type="file" accept="video/*">` 多选，仅存元信息（name/size）；写 `VideoPipelineDraft.materials[]` |
| 2 | 流水线配置 | 5 个 `ToggleCard`：添加字幕/生成封面/添加水印/去除静音/自动配乐；默认前 3 项勾选 |
| 3 | 生成 | `Film` 按钮 → 1.2s mock → 显示 Task ID + 完成提示 |

### 2.4 场景4 · 图片编辑（1 步，保持不变）

一步 `StepShell` 说明 + `onComplete` 自动跳 `/tools/image-editor`（M5）。

---

## 3. 跨步骤状态设计

### 3.1 存储模型

用模块级 `Map<sceneId, draft>` 存每个场景的 draft：

```ts
// wizard-state-cache.ts
const _sceneDrafts = new Map<string, unknown>()

export function getSceneDraft<D>(sceneId: string, initial: () => D): D {
  return _sceneDrafts.get(sceneId) ?? initial()
}
export function setSceneDraft<D>(sceneId: string, draft: D): void { ... }
export function clearSceneDraft(sceneId: string): void { ... }
```

三种 draft 接口：

- `AiWritingDraft` — 8 字段（platformIds/topic/titleCandidates/title/tags/body/published/publishedAt）
- `AiImageDraft` — 5 字段（referencePreview/agentId/imageTypeId/generatedUrls/generatedTaskId）
- `VideoPipelineDraft` — 3 字段（materials/config/taskId）

### 3.2 与 `_agentIdCache` 的桥接

`AgentPickerStep` 已经有自己的 `_agentIdCache`，且派发 `prism-wizard:agent-selected` CustomEvent。为了不重构 M2，我提供了 `subscribeAgentChangeToDraft()`：

- 幂等（只绑定一次）
- 监听 CustomEvent，把 `agent_id` 写入 `AiImageDraft.agentId`
- 由 `AiImageAgentStep` 组件挂载时调用

这样后续步骤（生成/结果）无需重读 AgentPicker 的 cache，直接从 AI_IMAGE 场景 draft 里拿即可。

### 3.3 生命周期

- 步骤切换（`SET_STEP`）→ 组件 remount → 从 cache 恢复 draft ✅
- Wizard 卸载（"返回场景列表"/"重置"）→ `ScenarioWizardBlock` 的 `useEffect` cleanup 调 `resetScenarioDraft(scene.id)` 清理
- 浏览器刷新 → 内存丢失（可接受，M1/M2 也是这个语义）

### 3.4 Patch-style 保存

`saveAiWritingDraft(patch: Partial<AiWritingDraft>)` 内部做 `{ ...loadAiWritingDraft(), ...patch }`：

- 各步骤只关心自己的字段（步骤1只 patch `platformIds`，步骤2只 patch `topic`）
- 避免同一 step 内多次点击导致陈旧 snapshot 覆盖其他字段
- 也避免与 AgentPicker 的 CustomEvent 写入发生竞态

---

## 4. 设计取舍

1. **不引入 `@testing-library/react`**：延续 M4/M1 的取舍，抽纯函数（`mockAi*`、cache API）+ 单测；DOM 交互留给未来的 `userEvent` 套件。
2. **不接入真实后端**：所有 API 调用都是 mock（`setTimeout` + 本地结果）。理由：
   - M4 场景引导的目的是"引导用户走通流程"，不是"完成业务闭环"
   - 真实 AI 生图 / 8 平台发布都需要后端配合，超出本次范围
   - mock 保持最小改动 + 可预测的测试行为
3. **素材图仅本地预览**：与 M1 `image-studio/page.tsx` 保持一致（M1 所有 provider 的 `maxReferenceImages=0`，传参考图后端会 400）。
4. **图片类型只用 4 种常用**：复用 `lib/image-studio.ts::IMAGE_TYPES` 常量，与 M1 一致；后续要扩到澜途 PRD 的 21 种，改常量即可。
5. **URL query 保持 scene/step/done 三键**：draft 数据不序列化到 URL（8 平台 × 正文全文会撑爆地址栏）；仅内存保存。分享链接只能共享"步骤进度"，不能共享"用户填的具体内容"。
6. **`ScenarioGrid` / `ScenarioCard` 保持对外 API 不变**：只做内部步骤填充，不影响任何调用方。

---

## 5. 测试

### 5.1 静态检查

```
npx tsc --noEmit
# 0 errors
```

### 5.2 单元/组件测试

```
npm test
Test Files  13 passed (13)
     Tests  297 passed (297)
```

**新增 15 用例**（282 → 297）：

| 测试文件 | 新增 | 覆盖点 |
|---|---:|---|
| `scenarios.test.tsx` | +9 | 8 平台列表齐全（label 数组严格匹配）+ 3 个 mock 函数（3 候选、含关键词、空输入回落、5 标签、唯一 URL、中文 URL encode） |
| `wizard-state-cache.test.ts` | +6 | `getSceneDraft` 未缓存回落 initial / `setSceneDraft` 后再 get / `clearSceneDraft` 回落 / `clearAllSceneDrafts` 清空 / 多 scene 隔离 / VideoPipeline 默认 config |

### 5.3 回归

- 原有 282 用例全部通过（M1 后端 74 / M2 25 / M3 51 / M4 core 46 / M5 13 / image-studio 61 等）
- `scenarios.test.tsx` 从 15 增至 24（+9）
- 新增 `wizard-state-cache.test.ts`（6 用例）

---

## 6. 关键实现细节

### 6.1 AI 生图场景的智能体桥接

`AgentPickerStep` 的 `handleSelect` 会派发 `CustomEvent("prism-wizard:agent-selected", { detail: { agent_id } })`。
`subscribeAgentChangeToDraft()` 在 `AiImageAgentStep` 挂载时监听该事件，把 agent_id 写入 `AiImageDraft.agentId`，后续步骤（生成/结果）直接读 draft 拿到。这样避免让 AgentPickerStep 反向依赖 wizard 内部 API。

### 6.2 Mock 生成函数的稳定性

- `mockAiGenerateImages(seed, count)` 用 `seed-${i+1}` 作 picsum 的种子后缀，同一 seed 每次生成的 URL 集稳定（可测试）
- `mockAiGenerateContent(topic)` 的标题/标签/正文都是 `topic` 的字符串模板，topic 为空时回落到 "新内容" 默认
- `mockAiSuggestTopics(hint)` 空输入时回落到 "内容创作"，保证 UI 不会因为没填选题而卡住

### 6.3 文件预览缓存

`FilePicker` 用 `name+size+lastModified` 作为 key 缓存 dataURL，避免同一 File 重复 `FileReader` 调用。图片缩略图在 `showPreview` 模式下渲染成 3 列网格。

---

## 7. 遗留问题

| 项 | 说明 | 后续处理 |
|---|---|---|
| **真实后端接入** | 所有 mock（AI 生图 / AI 生成内容 / 视频流水线 / 8 平台发布）需要后端就绪后替换 | 每处都有清晰的 mock 位置（`setTimeout` + 本地数组），替换点单一 |
| **DOM 交互测试** | 未覆盖 `userEvent.click` 触发步骤切换 / draft 持久化 / AgentPicker 事件桥接 | 与 M4/M1 一致的取舍；如需覆盖建议单独开任务安装 `@testing-library/react` |
| **URL 不携带 draft** | 分享链接只能共享 step 进度，不能共享用户填的具体内容 | 内存语义一致于 M1/M2；如需持久化可后续接入服务端保存或 IndexedDB |
| **`PUBLISH_PLATFORMS` 8 平台与 campaigns 页面的一致性** | 步骤1 的 8 平台 ID 与 `/campaigns` 页面的账号矩阵 ID 需要一致 | 当前是 ID 约定；接入真发布时需要对齐 |
| **`image-studio.ts::IMAGE_TYPES` 与 Wizard 步骤 3 同步** | Wizard 直接消费 M1 常量；如果 M1 扩展到 21 种，Wizard 自动跟随 | 无需改动 |
| **Community 版视频/写稿场景** | AI 写稿 / 视频流水线不做 Pro 配额判断 | 澜途 PRD 未明确这两个场景的付费门槛；后续按业务需要加 |

---

## 8. 相关文件

- `prism_frontend/src/components/wizard/scenarios.tsx` — 修改（骨架 → 实际功能）
- `prism_frontend/src/components/wizard/wizard-state-cache.ts` — 新增
- `prism_frontend/src/components/wizard/scenario-guide.tsx` — 修改（清理 draft）
- `prism_frontend/src/components/wizard/index.ts` — 修改（barrel 出口）
- `prism_frontend/src/components/wizard/__tests__/scenarios.test.tsx` — 修改（+9 用例）
- `prism_frontend/src/components/wizard/__tests__/wizard-state-cache.test.ts` — 新增
- `docs/dev-reports/2026-10-16-m4-steps-fill.md` — 本文档

**参考**：
- `docs/dev-reports/2026-10-16-m4-implementation.md` — M4 骨架
- `docs/dev-reports/2026-10-16-m1-frontend.md` — M1 AI 生图工作台
- `docs/dev-reports/2026-10-16-m2-implementation.md` — M2 智能体 + authFetch
- `prism_frontend/src/lib/image-studio.ts` — IMAGE_TYPES / buildEditorUrl / isAcceptedImage

---

*完成于 2026-10-20*
