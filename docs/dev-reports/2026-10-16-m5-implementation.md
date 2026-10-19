# M5 图片编辑器实现报告

- 报告日期：2026-10-18
- 关联规划：`docs/dev-reports/2026-10-16-module-replication-plan.md` §3.5
- 落地位置：`prism_frontend/src/app/tools/image-editor/`

## 1. 实现的文件清单

### 新增

| 文件 | 作用 |
|------|------|
| `prism_frontend/src/lib/image-editor-logic.ts` | 纯逻辑层：裁剪比例预设、百分比→像素换算、图像烘焙（`cropImageToCanvas` / `buildCropDataURL`）、CSS 滤镜组装（`buildFilterCss` / `applyImageFilters`）、`createHistory` 撤销重做栈、`createBaseCanvas`（fabric.Canvas 初始化）、`exportCanvasToBlob`（导出 PNG/JPG/WebP） |
| `prism_frontend/src/lib/__tests__/image-editor-logic.test.ts` | 13 个单元测试，覆盖 CROP_PRESETS、createHistory、normalizePercentCrop、normalizeExportFormat、buildFilterCss |
| `prism_frontend/src/components/image-editor/image-editor.tsx` | `"use client"` 组件，四阶段流水线（upload → crop → edit → export），使用 `react-image-crop`、`fabric`、`react-dropzone`、shadcn/ui |
| `prism_frontend/src/app/tools/image-editor/page.tsx` | Next.js App Router 页面，包 PageHeader + ImageEditor |

### 修改

| 文件 | 变更 |
|------|------|
| `prism_frontend/package.json` | 新增依赖 `fabric@^7.4.0`、`react-image-crop@^11.1.2` |
| `prism_frontend/src/components/layout/sidebar-new.tsx` | "资源"分组新增 `{ label: "图片编辑器", href: "/tools/image-editor", icon: ImageIcon }` |

## 2. 功能清单

- **上传**
  - 拖拽或点击上传 JPG / PNG / WebP
  - 文件类型白名单校验（`Accept` + `File.type` 双重）
  - FileReader 转 dataURL，浏览器本地处理，无后端上传
- **裁剪**（react-image-crop v11）
  - 6 种比例：自由 / 1:1 / 3:4 / 4:3 / 16:9 / 9:16
  - 百分比裁剪 → 像素裁剪换算，边界保护（`pixelCropFromPercent`）
  - 应用裁剪后烘焙为 PNG dataURL，作为编辑阶段的输入
- **编辑**（fabric.js v7）
  - 加文字：白字黑描边，居中，自适应画布尺寸
  - 加形状：矩形、圆形、三角、箭头（`Line` + `Triangle` 组合）
  - 拖拽 / 缩放 / 旋转 / 删除（fabric 内置交互 + 删除选中）
  - 滤镜：亮度、对比度、饱和度（CSS filter 实时预览，导出前烘焙为真实像素）
  - 撤销 / 重做：基于 `canvas.toJSON()` 快照栈，深度上限 30
- **导出**
  - 支持 PNG / JPG（默认 PNG）
  - JPG 质量滑条 50–100
  - 通过底层 `canvas.toBlob` 走 fetch + re-encode，保证大图片可用
  - 文件名保留原文件主干 + 新扩展名

## 3. 测试结果

```
# tsc
$ npx tsc --noEmit
# 0 errors

# vitest
$ npx vitest run
Test Files  6 passed (6)
     Tests  122 passed (122)
```

新增 13 个测试全部通过：
- `CROP_PRESETS` 覆盖 6 种比例
- `createHistory` push/undo/redo、redo 分支截断、maxDepth、clear
- `normalizePercentCrop` 边界钳制、NaN 兜底、80% 默认
- `normalizeExportFormat` 别名兼容、未知格式抛错
- `buildFilterCss` 正负饱和度、CSS 拼装

## 4. 遗留问题

1. **jsdom 无 canvas 2D context**：项目 `vitest.config.ts` 默认 `environment: "node"`；jsdom 也未装 `node-canvas`，因此 `cropImageToCanvas` / `buildCropDataURL` / `applyImageFilters` / `exportCanvasToBlob` 只能依赖真实浏览器环境验证。当前测试覆盖了纯像素换算（`pixelCropFromPercent`）与 CSS 拼装，DOM 相关分支需在浏览器端手工或 `e2e` 覆盖。
2. **fabric Canvas → React SSR**：fabric.js 依赖 DOM，全程位于 `"use client"` 组件，`createBaseCanvas` 只在阶段跳转时通过 `await` 创建；`useEffect` cleanup 里调用 `canvas.dispose()` 防止内存泄漏（对应规划 §3.5.4）。
3. **滤镜为 CSS 近似**：亮度 / 对比度 / 饱和度通过 `ctx.filter` 烘焙，符合主流浏览器语义；饱和度在部分老内核上可能退化为 `hue-rotate` 近似（未启用），当前 Chrome/Safari/Firefox 均支持。
4. **未接入 `/api/v1/files/upload`**：本轮只做本地裁剪 + 编辑 + 导出下载，M5 规划里"可选上传到素材库"的入口留待 M1/M2 打通后再补。
5. **未接入素材管理页的"图片"按钮**：规划 §3.5.5 提到 M1 完成后从 `material-editor-sheet.tsx` 增加"进入编辑器"按钮，本轮未触碰，避免重构无关代码。
6. **未实现 layer-panel / export-dialog 独立组件**：功能上完全覆盖（画布直接可拖拽、导出走内联 Select），为保持最小改动未拆分文件。
