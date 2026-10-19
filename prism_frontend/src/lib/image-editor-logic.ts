/**
 * M5 图片编辑器 —— 核心逻辑层
 *
 * 保持为纯模块，便于单元测试（vitest，node 环境）。
 * - `CROP_PRESETS` / `getAspectValue`：裁剪比例（含自由比例）
 * - `History<T>`：撤销 / 重做（栈）
 * - `pixelCropFromPercent`：把 react-image-crop 的百分比裁剪换算成像素裁剪
 * - `cropImageToCanvas`：把像素裁剪结果烘焙到 HTMLCanvasElement
 * - `applyImageFilters`：以 CSS 滤镜模拟亮度/对比度/饱和度（saturate 用 hue-rotate 叠加近似）
 * - `buildCropDataURL`：把 file/dataURL 直接烘焙成裁剪后的 dataURL，便于测试与后续 canvas 加载
 * - `createBaseCanvas`：fabric.Canvas 包装，避免在 UI 里混用 new Canvas 与 createCanvas
 * - `exportCanvasToBlob`：导出 PNG / JPG / WebP 的 canvas blob
 *
 * 依赖：
 * - fabric.js 7.x —— MIT
 * - react-image-crop 11.x —— MIT
 */
import { Canvas, Circle, Image as FabricImage, Line, Rect, Text, Triangle } from "fabric"

/* ------------------------------------------------------------------ */
/* 裁剪比例预设                                                        */
/* ------------------------------------------------------------------ */

export const CROP_PRESETS = [
  { id: "free", label: "自由", ratio: null },
  { id: "1:1", label: "1:1", ratio: 1 },
  { id: "3:4", label: "3:4", ratio: 3 / 4 },
  { id: "4:3", label: "4:3", ratio: 4 / 3 },
  { id: "16:9", label: "16:9", ratio: 16 / 9 },
  { id: "9:16", label: "9:16", ratio: 9 / 16 },
] as const

export type CropPresetId = (typeof CROP_PRESETS)[number]["id"]

export function getAspectValue(id: CropPresetId): number | null {
  const preset = CROP_PRESETS.find((p) => p.id === id)
  return preset ? preset.ratio : null
}

/* ------------------------------------------------------------------ */
/* 撤销 / 重做历史                                                     */
/* ------------------------------------------------------------------ */

export interface History<T> {
  push: (item: T) => void
  undo: () => T | undefined
  redo: () => T | undefined
  clear: () => void
  canUndo: () => boolean
  canRedo: () => boolean
  getSnapshot: () => T[]
}

export function createHistory<T>(initial: T, maxDepth = 50): History<T> {
  const stack: T[] = [initial]
  let pointer = 0

  return {
    push(item) {
      // 新动作会截断 redo 分支
      stack.splice(pointer + 1)
      stack.push(item)
      pointer = stack.length - 1
      if (stack.length > maxDepth) {
        stack.shift()
        pointer -= 1
      }
    },
    undo() {
      if (pointer <= 0) return undefined
      pointer -= 1
      return stack[pointer]
    },
    redo() {
      if (pointer >= stack.length - 1) return undefined
      pointer += 1
      return stack[pointer]
    },
    clear() {
      stack.length = 0
      stack.push(initial)
      pointer = 0
    },
    canUndo: () => pointer > 0,
    canRedo: () => pointer < stack.length - 1,
    getSnapshot: () => [...stack],
  }
}

/* ------------------------------------------------------------------ */
/* 裁剪像素换算与烘焙                                                  */
/* ------------------------------------------------------------------ */

export interface PixelCropRect {
  x: number
  y: number
  width: number
  height: number
}

export function pixelCropFromPercent(
  percentCrop: { x: number; y: number; width: number; height: number },
  imgWidth: number,
  imgHeight: number,
): PixelCropRect {
  const width = Math.max(1, Math.round(percentCrop.width * imgWidth))
  const height = Math.max(1, Math.round(percentCrop.height * imgHeight))
  const x = Math.max(0, Math.min(imgWidth - width, Math.round(percentCrop.x * imgWidth)))
  const y = Math.max(0, Math.min(imgHeight - height, Math.round(percentCrop.y * imgHeight)))
  return { x, y, width, height }
}

export async function cropImageToCanvas(
  source: HTMLImageElement | HTMLCanvasElement,
  crop: PixelCropRect,
  targetCanvas: HTMLCanvasElement,
): Promise<void> {
  const ctx = targetCanvas.getContext("2d")
  if (!ctx) throw new Error("2D canvas context unavailable")
  targetCanvas.width = crop.width
  targetCanvas.height = crop.height
  ctx.clearRect(0, 0, crop.width, crop.height)
  ctx.drawImage(
    source,
    crop.x, crop.y, crop.width, crop.height,
    0, 0, crop.width, crop.height,
  )
}

/**
 * 通过 file / dataURL / blobURL 直接生成裁剪后的 dataURL。
 * 供测试与"跨组件传值"使用；正常路径由 UI 层调用同一套像素换算逻辑。
 */
export async function buildCropDataURL(
  source: File | string,
  percentCrop: { x: number; y: number; width: number; height: number },
): Promise<string> {
  const srcURL = typeof source === "string" ? source : URL.createObjectURL(source)
  const img = await loadHTMLImage(srcURL)
  const percent = normalizePercentCrop(percentCrop)
  const pixelCrop = pixelCropFromPercent(percent, img.naturalWidth, img.naturalHeight)

  const canvas = document.createElement("canvas")
  canvas.width = pixelCrop.width
  canvas.height = pixelCrop.height
  const ctx = canvas.getContext("2d")
  if (!ctx) throw new Error("2D canvas context unavailable")
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  ctx.drawImage(
    img,
    pixelCrop.x, pixelCrop.y, pixelCrop.width, pixelCrop.height,
    0, 0, pixelCrop.width, pixelCrop.height,
  )

  if (!srcURL.startsWith("data:")) {
    URL.revokeObjectURL(srcURL)
  }
  return canvas.toDataURL("image/png")
}

export function normalizePercentCrop(
  percentCrop: { x?: number; y?: number; width?: number; height?: number },
): { x: number; y: number; width: number; height: number } {
  // 用 fallbackSafe 把 NaN/Infinity/undefined 都视作"未提供"，再应用默认值
  const x = clamp01(fallbackSafe(percentCrop.x, 0))
  const y = clamp01(fallbackSafe(percentCrop.y, 0))
  const width = clamp01(fallbackSafe(percentCrop.width, 0.8))
  const height = clamp01(fallbackSafe(percentCrop.height, 0.8))
  // 保证右下角不出界，避免出现负宽高；使用 epsilon 规避浮点尾差
  const widthClamped = clamp01(Math.max(0.0001, Math.min(width, 1 - x)))
  const heightClamped = clamp01(Math.max(0.0001, Math.min(height, 1 - y)))
  return { x, y, width: widthClamped, height: heightClamped }
}

/* ------------------------------------------------------------------ */
/* 滤镜                                                                */
/* ------------------------------------------------------------------ */

export interface ImageFilterAdjustments {
  /** 亮度百分比：100 = 不变 */
  brightness: number
  /** 对比度百分比：100 = 不变 */
  contrast: number
  /** 饱和度百分比：100 = 不变；负值按 0 处理 */
  saturation: number
}

export function buildFilterCss({ brightness, contrast, saturation }: ImageFilterAdjustments): string {
  return `brightness(${brightness}%) contrast(${contrast}%) saturate(${Math.max(0, saturation)}%)`
}

/**
 * 原生 canvas.filter 支持 brightness/contrast/saturate；对不支持 saturate 的
 * 环境提供 hue-rotate 叠加的近似实现（不影响主流程）。
 */
export function applyImageFilters(
  source: HTMLImageElement | HTMLCanvasElement,
  adjustments: ImageFilterAdjustments,
  targetCanvas: HTMLCanvasElement,
): HTMLCanvasElement {
  targetCanvas.width = source.width
  targetCanvas.height = source.height
  const ctx = targetCanvas.getContext("2d")
  if (!ctx) throw new Error("2D canvas context unavailable")

  ctx.clearRect(0, 0, targetCanvas.width, targetCanvas.height)
  ctx.filter = buildFilterCss(adjustments)
  ctx.drawImage(source, 0, 0)
  ctx.filter = "none"

  // 兜底：saturate 不支持时，用 hue-rotate(0deg → 200deg → -200deg) 的三次绘制近似饱和
  if (adjustments.saturation < 100) {
    const factor = Math.max(0, Math.min(1, (100 - adjustments.saturation) / 100))
    if (factor > 0.02) {
      const intermediate = document.createElement("canvas")
      intermediate.width = targetCanvas.width
      intermediate.height = targetCanvas.height
      const ictx = intermediate.getContext("2d")!
      ictx.drawImage(source, 0, 0)
      // saturate(0) ≈ hue-rotate(180deg) 两次，取近似 200/-200
      ictx.filter = `hue-rotate(${200 * factor}deg)`
      ictx.drawImage(source, 0, 0)
      ictx.filter = `hue-rotate(${-200 * factor}deg)`
      ictx.drawImage(source, 0, 0)
      ictx.filter = "none"

      ctx.globalAlpha = factor
      ctx.drawImage(intermediate, 0, 0)
      ctx.globalAlpha = 1
    }
  }
  return targetCanvas
}

/* ------------------------------------------------------------------ */
/* Fabric Canvas 辅助                                                  */
/* ------------------------------------------------------------------ */

/**
 * 由图片 dataURL 创建 fabric.Canvas；canvas 尺寸默认等于图片自然尺寸，
 * 避免 fabric.Image 异步加载导致尺寸不一致。
 */
export async function createBaseCanvas(
  src: string,
  width?: number,
  height?: number,
): Promise<InstanceType<typeof Canvas>> {
  const { naturalWidth, naturalHeight } = await loadImageMeta(src)
  const canvasWidth = width ?? naturalWidth
  const canvasHeight = height ?? naturalHeight

  // 使用离屏 element，交由 UI 层用 replaceWith 挂载到 DOM
  const element = document.createElement("canvas")
  element.style.width = `${canvasWidth}px`
  element.style.height = `${canvasHeight}px`

  const canvas = new Canvas(element, { width: canvasWidth, height: canvasHeight })
  canvas.backgroundColor = "white"
  const image = await FabricImage.fromURL(src, { crossOrigin: "anonymous" })
  // fabric.Image 默认以自然尺寸放置；若 canvas 尺寸不同，按比例缩放
  const scale = Math.min(
    canvasWidth / image.width,
    canvasHeight / image.height,
    1,
  )
  image.set({
    left: (canvasWidth - image.width * scale) / 2,
    top: (canvasHeight - image.height * scale) / 2,
    scaleX: scale,
    scaleY: scale,
  })
  canvas.add(image)
  canvas.renderAll()
  return canvas
}

/* ------------------------------------------------------------------ */
/* 导出                                                                */
/* ------------------------------------------------------------------ */

export type ImageExportFormat = "image/png" | "image/jpeg" | "image/webp"

export function normalizeExportFormat(fmt: string): ImageExportFormat {
  if (fmt === "image/png" || fmt === "png") return "image/png"
  if (fmt === "image/jpeg" || fmt === "image/jpg" || fmt === "jpeg" || fmt === "jpg") return "image/jpeg"
  if (fmt === "image/webp" || fmt === "webp") return "image/webp"
  throw new Error(`Unsupported export format: ${fmt}`)
}

/**
 * 从 fabric.Canvas 底层 HTMLCanvasElement 导出 Blob。
 * fabric v7 的 StaticCanvas.toBlob 直接返回 Promise<Blob|null>。
 */
export async function exportCanvasToBlob(
  canvas: InstanceType<typeof Canvas>,
  options: { format?: ImageExportFormat; quality?: number; multiplier?: number } = {},
): Promise<Blob> {
  const format = options.format ?? "image/png"
  const quality = options.quality
  const multiplier = options.multiplier ?? 1
  // fabric.ImageFormat 只接受 'jpeg'|'png'|'webp'；这里把 image/x 前缀剥掉
  const fabricFormat = format.replace(/^image\//, "") as "png" | "jpeg" | "webp"
  const blob = await canvas.toBlob({ format: fabricFormat, quality, multiplier })
  if (!blob || blob.size === 0) throw new Error("Export produced an empty blob")
  return blob
}

/* ------------------------------------------------------------------ */
/* 内部工具                                                            */
/* ------------------------------------------------------------------ */

function clamp01(v: number): number {
  if (!Number.isFinite(v)) return 0
  return Math.max(0, Math.min(1, v))
}

/** 若 v 缺失或非有限数，返回 fallback，避免 NaN 污染默认值 */
function fallbackSafe(v: number | undefined, fallback: number): number {
  if (v === undefined || !Number.isFinite(v)) return fallback
  return v
}

function loadImageMeta(src: string): Promise<{ naturalWidth: number; naturalHeight: number }> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = "anonymous"
    img.onload = () => resolve({ naturalWidth: img.naturalWidth, naturalHeight: img.naturalHeight })
    img.onerror = () => reject(new Error("Failed to load image metadata"))
    img.src = src
  })
}

function loadHTMLImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = "anonymous"
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error("Failed to load image"))
    img.src = src
  })
}
