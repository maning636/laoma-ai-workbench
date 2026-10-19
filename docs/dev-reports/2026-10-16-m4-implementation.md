# M4 工作流自动化模块（场景引导 Wizard）实施报告

- 报告日期：2026-10-18
- 模块负责人：M4 前端子代理
- 前置阅读：
  - `docs/dev-reports/2026-10-16-module-replication-plan.md`（M4 章节）
  - `docs/dev-reports/2026-10-16-lantyou-api-audit.md`（澜途首页"功能引导"）

---

## 1. 实现的文件清单

### 新增文件（7 个）

| 路径 | 作用 |
|---|---|
| `prism_frontend/src/components/wizard/wizard-core.ts` | 纯 reducer + 判定函数（可脱离 React 测试） |
| `prism_frontend/src/components/wizard/url-sync.ts` | URL query 同步的纯函数（parse/build 双向） |
| `prism_frontend/src/components/wizard/wizard.tsx` | 通用 `Wizard` 组件 + `Stepper` + `SceneWizardLink` |
| `prism_frontend/src/components/wizard/scenarios.tsx` | 4 个场景定义 + `ScenarioGrid` + `ScenarioCard` |
| `prism_frontend/src/components/wizard/scenario-guide.tsx` | 首页功能引导区块 `ScenarioGuide` |
| `prism_frontend/src/components/wizard/index.ts` | Barrel 出口 |
| `prism_frontend/src/components/wizard/__tests__/*.test.{ts,tsx}` | 3 份测试文件（46 用例） |

### 修改文件（1 个）

| 路径 | 变更 |
|---|---|
| `prism_frontend/src/app/page.tsx` | 引入 `ScenarioGuide`，在 stat cards 与任务表之间插入功能引导区块（1 行 import + 1 行 JSX） |

### 未修改
- 未新增依赖（复用 shadcn `Button/Card/Badge/Separator` + `lucide-react`）
- 未改动 M5 图片编辑器、M3 计费、M1 生图任何代码
- 未改动侧边栏菜单

---

## 2. 场景卡片设计

参考澜途首页的"功能引导"卡片（选场景→按步骤开始），设计为 4 卡横排网格：

| 场景 | 目标路径 | 步骤 | 状态 |
|---|---|---|---|
| AI 写稿发布 | `/campaigns` | 4 步（选平台→选题→AI生成→发布） | 已上线 |
| AI 生图 | `/fusion/model-market` | 4 步（上传→类型→生成→编辑） | 即将接入 |
| 视频流水线 | `/video-pipeline` | 3 步（选素材→配置→生成） | 已上线 |
| 图片编辑 | `/tools/image-editor` | 1 步（直接进入编辑器） | 已上线 |

每张卡片信息密度：
- **图标 + 状态徽章**（左上/右上）
- **标题 + 描述**（引用现有功能命名）
- **步数标签 + 去开始按钮**（右下）

复用 shadcn 组件（`Card`、`Button`）+ Tailwind 类，不引入新 UI 库。

---

## 3. Wizard 状态机设计

### 3.1 States

```ts
type WizardStatus = "idle" | "stepping" | "done"

interface WizardState {
  scene: string | null   // 场景 id
  step: number           // 当前步骤 0-based
  total: number          // 总步骤数
  status: WizardStatus
}
```

### 3.2 Actions

| Action | 语义 |
|---|---|
| `SELECT_SCENE {scene, total, step?}` | 选择场景，进入 stepping |
| `NEXT` | 前进 1 步；到末步时进入 done |
| `PREV` | 后退 1 步（step=0 时 no-op） |
| `SET_STEP {step}` | 直接跳转（含 Stepper 点击、URL 恢复） |
| `DONE` | 强制标记完成（step=total-1） |
| `RESET` | 清空到初始 idle 状态 |

### 3.3 转换规则

- `NEXT` 在 `status=done` 时为 no-op
- `NEXT` 到末步时**自动转 done**（无需显式 DONE）
- `PREV` 在 `step=0` 时为 no-op
- `SET_STEP` 在 `scene=null` 时为 no-op（防御性）
- `step` 始终 clamp 到 `[0, total-1]`
- `total=0` 时保持 `idle`，禁止进入 stepping

辅助判定函数（供 UI 用）：`canNext` / `canPrev` / `isLastStep`。

---

## 4. URL query 同步方式

采用双向同步，query key 三枚：

```
/?scene=<sceneId>&step=<N>&done=1
```

### 4.1 URL → state（初始挂载）

`Wizard` 组件挂载时通过 `parseWizardQuery(searchParams, total)` 读取：
- `?scene` 匹配本组件的 `scene` prop 才采用
- `step` 经过 `clampParseStep` 钳制到 `[0, total-1]`
- `done=1` 时 `status=done` 且 `step` 归位到末步
- 场景不匹配时保持干净的 stepping 初始态

### 4.2 state → URL（用户操作后）

每次 `state.step` 或 `state.status` 变化，通过 `buildWizardQuery` 计算新 query，`router.replace` 更新地址栏：
- 保留其他 query 键（如 `q=searchTerm`）
- `done=false` 时移除 `done`
- `RESET` 时移除 `scene/step/done`，回到干净首页

### 4.3 关键设计决策

- **用 `router.replace` 而非 `push`**：避免每次点击下一步/上一步都压栈，浏览器返回键仍回到场景列表
- **URL 是唯一真源**：刷新页面 / 分享链接 / 前进后退都能正确恢复
- **纯函数抽出到 `url-sync.ts`**：便于脱离 React 单测

---

## 5. 测试结果

### 5.1 静态检查

```
npx tsc --noEmit   # ✅ 0 error
```

### 5.2 单元/组件测试

```
npm test
Test Files  9 passed (9)
     Tests  168 passed (168)
```

**新增 46 个测试用例**（原 122 保持通过）：

| 测试文件 | 用例数 | 覆盖点 |
|---|---|---|
| `wizard-core.test.ts` | 19 | reducer 全动作、`SELECT_SCENE` clamp、`NEXT`/`PREV` 边界、`DONE`/`RESET`、`canNext/canPrev/isLastStep`、`clampStep` |
| `scenarios.test.tsx` | 14 | 4 场景 id/步数/target 校验、`getScenarioById` 命中/未命中 |
| `url-sync.test.ts` | 13 | `parseWizardQuery`（scene/step/done/clamp/idle）、`buildWizardQuery`（增删改、保留其他键、RESET 清键）、`hasWizardQuery`、`clampParseStep` |

覆盖任务要求：
- ✅ 场景卡片渲染（4 场景全在）——`scenarios.test.tsx`
- ✅ Wizard 步骤导航（上/下/完成/重置）——`wizard-core.test.ts`
- ✅ URL query 同步（scene/step/done 双向）——`url-sync.test.ts`
- ✅ 状态机转换（含 clamp/no-op/边界）——`wizard-core.test.ts`

> 未做 DOM 交互测试（如 `userEvent.click`）因为项目未安装 `@testing-library/react`；引入该依赖超出 M4 最小改动范围。reducer + 纯函数已经覆盖了状态转换与 URL 同步的全部核心逻辑。

### 5.3 类型与运行时防御

- `Wizard` 在 `steps=[]` 时不渲染步骤区（防御性空态）
- `parseWizardQuery` 对 `NaN`、`step<0`、`step>=total` 都做了钳制
- reducer 的 `SELECT_SCENE` / `SET_STEP` 都对边界做了 clamp

---

## 6. 遗留问题（后续模块接入点）

### 6.1 骨架步骤（当前为占位卡片，需后续模块接入真实业务）

| 场景 | 步骤 | 后续动作 |
|---|---|---|
| AI 写稿发布 | 步骤 2「选题」 | 接入 AI 生成选题（`fusion_ai` LLM） |
| AI 写稿发布 | 步骤 3「AI 生成内容」 | 接入云端 LLM（标题/标签/正文） |
| AI 写稿发布 | 步骤 4「确认并发布」 | 接入 8 平台矩阵发布 API |
| AI 生图 | 步骤 1「上传原图」 | M1 完成后接入素材上传 |
| AI 生图 | 步骤 2「图片类型」 | M1 完成后接入 21 种类型选择 |
| AI 生图 | 步骤 3「生成」 | 接入 gpt-image-1 / ComfyUI 后端 |
| AI 生图 | 步骤 4「编辑/发布」 | 跳转编辑器 + 发布中心 |
| 视频流水线 | 步骤 1「选择素材」 | 接入素材库 / Easel 收件箱 |
| 视频流水线 | 步骤 2「流水线配置」 | 接入剪辑/字幕/封面/水印步骤 |
| 视频流水线 | 步骤 3「生成」 | 接入 Easel 异步执行 |

### 6.2 其他待办

- **平台多选未持久化**：步骤 1「选平台」当前的多选状态在切换步骤时会丢，后续接入真实业务流程时需在 Wizard 内维护跨步骤数据模型（可用 `useRef` 存 draft，或提升到 `dispatch` payload）
- **DOM 交互测试**：如需覆盖 Stepper 点击、按钮 disabled 态，需引入 `@testing-library/react`（超出本模块范围）
- **国际化**：目前所有文案为中文硬编码，与项目其他模块一致；未来若接入 i18n 需集中翻译
- **完成后的动作**：`onComplete` 默认仅 image-editor 自动跳转；其他场景在 done 视图提供手动跳转按钮，避免误操作

---

## 7. 关键实现取舍

1. **不引入 Trigger.dev / n8n**：Prism-Fusion 已有 celery 做异步编排，前端只承担状态机；n8n 为 fair-code 非 OSI，license 风险规避
2. **URL 是唯一真源**：分享链接（`/?scene=ai-writing&step=2`）在同事/客服场景直接可用
3. **纯函数抽离**：`wizard-core.ts` + `url-sync.ts` 与 React 完全解耦，测试无需 DOM
4. **最小改动**：首页只加了一行 `<ScenarioGuide />` 区块；未重构 `page.tsx` 现有 stat cards / 任务表 / 快捷入口
