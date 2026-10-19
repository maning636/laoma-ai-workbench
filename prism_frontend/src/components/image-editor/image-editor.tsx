"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import ReactCrop from "react-image-crop"
import "react-image-crop/dist/ReactCrop.css"
import { Canvas, Circle, Line, Rect, Text, Triangle } from "fabric"
import { useDropzone } from "react-dropzone"
import {
  Circle as CircleIcon,
  Download,
  Loader2,
  RotateCcw,
  Scissors,
  Square,
  Type,
  Undo2,
  UploadCloud,
  Redo2,
  Triangle as TriangleIcon,
  ArrowUpRight,
  Trash2,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useToast } from "@/components/ui/use-toast"
import { cn } from "@/lib/utils"
import {
  CROP_PRESETS,
  createBaseCanvas,
  createHistory,
  getAspectValue,
  ImageExportFormat,
  ImageFilterAdjustments,
  type CropPresetId,
  pixelCropFromPercent,
  normalizePercentCrop,
} from "@/lib/image-editor-logic"

type Stage = "upload" | "crop" | "edit" | "export"

type CanvasRef = InstanceType<typeof Canvas>

const ACCEPTED_MIME = new Set(["image/jpeg", "image/png", "image/webp"])
const HISTORY_LIMIT = 30

/** Fabric 对象的 JSON 化快照（撤销/重做用）。 */
type Snapshot = { json: string }

interface ImageEditorProps {
  /**
   * 初始图片 URL：若提供，则编辑器挂载时自动 fetch + 转 dataURL + 进入 crop 阶段。
   * 支持 http(s) 图片 URL；跨域失败时降级到上传阶段并 toast 提示。
   */
  initialUrl?: string
}

export function ImageEditor({ initialUrl }: ImageEditorProps = {}) {
  const [stage, setStage] = useState<Stage>("upload")
  const [srcDataURL, setSrcDataURL] = useState<string | null>(null)
  const [fileName, setFileName] = useState<string>("")
  const [cropPresetId, setCropPresetId] = useState<CropPresetId>("free")
  const [percentCrop, setPercentCrop] = useState<{ x: number; y: number; width: number; height: number; unit: "%" }>({
    x: 0.1,
    y: 0.1,
    width: 0.8,
    height: 0.8,
    unit: "%",
  })
  const [exportFormat, setExportFormat] = useState<ImageExportFormat>("image/png")
  const [exportQuality, setExportQuality] = useState(0.92)
  const [exporting, setExporting] = useState(false)
  const [busy, setBusy] = useState(false)

  const [adjustments, setAdjustments] = useState<ImageFilterAdjustments>({
    brightness: 100,
    contrast: 100,
    saturation: 100,
  })

  const [historyVersion, setHistoryVersion] = useState(0)
  const [redoVersion, setRedoVersion] = useState(0)

  const { toast } = useToast()
  const fabricHostRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef<CanvasRef | null>(null)
  const baseImageDataURLRef = useRef<string | null>(null)
  const historyRef = useRef<ReturnType<typeof createHistory<Snapshot>> | null>(null)

  const cropAspect = getAspectValue(cropPresetId)

  /* ---------------- 上传 ---------------- */

  const cleanupFabric = useCallback(() => {
    const host = fabricHostRef.current
    const canvas = canvasRef.current
    canvasRef.current = null
    if (canvas) {
      try { canvas.dispose() } catch { /* ignore */ }
    }
    if (host) host.replaceChildren()
  }, [])

  const resetEditor = useCallback(() => {
    cleanupFabric()
    historyRef.current = null
  }, [cleanupFabric])

  useEffect(() => () => cleanupFabric(), [cleanupFabric])

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      const file = acceptedFiles[0]
      if (!file) return
      if (!ACCEPTED_MIME.has(file.type)) {
        toast({
          title: "格式不支持",
          description: `仅支持 JPG / PNG / WebP，收到：${file.type || file.name}`,
          variant: "destructive",
        })
        return
      }
      const reader = new FileReader()
      reader.onload = () => {
        const result = reader.result
        if (typeof result !== "string") return
        setSrcDataURL(result)
        setFileName(file.name)
        setPercentCrop({ x: 0.1, y: 0.1, width: 0.8, height: 0.8, unit: "%" })
        resetEditor()
        setStage("crop")
      }
      reader.onerror = () =>
        toast({ title: "读取失败", description: "无法读取该图片文件", variant: "destructive" })
      reader.readAsDataURL(file)
    },
    [toast, resetEditor],
  )

  // 通过 URL 预加载：M1 → M5 跳转携带 ?url=<imgUrl>
  useEffect(() => {
    if (!initialUrl) return
    let cancelled = false
    async function loadFromUrl(url: string) {
      try {
        const blob = await fetch(url, { mode: "cors" }).then((r) => {
          if (!r.ok) throw new Error(`HTTP ${r.status}`)
          return r.blob()
        })
        if (cancelled) return
        const dataUrl = await new Promise<string>((resolve, reject) => {
          const reader = new FileReader()
          reader.onload = () => {
            const result = reader.result
            if (typeof result === "string") resolve(result)
            else reject(new Error("invalid dataURL"))
          }
          reader.onerror = () => reject(new Error("FileReader 失败"))
          reader.readAsDataURL(blob)
        })
        if (cancelled) return
        setSrcDataURL(dataUrl)
        setFileName("remote-image")
        setPercentCrop({ x: 0.1, y: 0.1, width: 0.8, height: 0.8, unit: "%" })
        resetEditor()
        setStage("crop")
      } catch (e) {
        if (cancelled) return
        toast({
          title: "加载远程图片失败",
          description: e instanceof Error ? e.message : String(e),
          variant: "destructive",
        })
      }
    }
    void loadFromUrl(initialUrl)
    return () => {
      cancelled = true
    }
    // 只依赖 initialUrl：挂载时加载一次即可
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialUrl])

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "image/jpeg": [".jpg", ".jpeg"],
      "image/png": [".png"],
      "image/webp": [".webp"],
    },
    maxFiles: 1,
  })

  /* ---------------- 裁剪 -> 编辑 ---------------- */

  const handleApplyCrop = useCallback(async () => {
    const image = await loadImage(srcDataURL!)
    const pixel = pixelCropFromPercent(normalizePercentCrop(percentCrop), image.naturalWidth, image.naturalHeight)
    setBusy(true)
    try {
      const cropped = document.createElement("canvas")
      cropped.width = pixel.width
      cropped.height = pixel.height
      const ctx = cropped.getContext("2d")!
      ctx.drawImage(image, pixel.x, pixel.y, pixel.width, pixel.height, 0, 0, pixel.width, pixel.height)
      const croppedURL = cropped.toDataURL("image/png")
      setSrcDataURL(croppedURL)
      baseImageDataURLRef.current = croppedURL

      // 初始化 fabric 画布
      cleanupFabric()
      const canvas = await createBaseCanvas(croppedURL, pixel.width, pixel.height)
      canvasRef.current = canvas
      const host = fabricHostRef.current
      if (host) host.replaceChildren(canvas.getElement())
      canvas.on("object:modified", () => commitHistory())
      canvas.on("object:moving", () => {}) // no-op for stable typing
      canvas.renderAll()

      // 初始化历史栈
      historyRef.current = createHistory<Snapshot>({ json: canvas.toJSON() }, HISTORY_LIMIT)
      setAdjustments({ brightness: 100, contrast: 100, saturation: 100 })
      setHistoryVersion((v) => v + 1)
      setRedoVersion((v) => v + 1)
      setStage("edit")
    } catch (err) {
      toast({
        title: "裁剪失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      })
    } finally {
      setBusy(false)
    }
  }, [percentCrop, srcDataURL, toast])

  /* ---------------- 编辑 ---------------- */

  const commitHistory = useCallback(() => {
    const canvas = canvasRef.current
    const h = historyRef.current
    if (!canvas || !h) return
    h.push({ json: canvas.toJSON() })
    setHistoryVersion((v) => v + 1)
    setRedoVersion((v) => v + 1)
  }, [])

  const handleUndo = useCallback(() => {
    const canvas = canvasRef.current
    const h = historyRef.current
    if (!canvas || !h) return
    const snapshot = h.undo()
    if (!snapshot) return
    void canvas.loadFromJSON(snapshot.json)
    canvas.renderAll()
    setHistoryVersion((v) => v + 1)
    setRedoVersion((v) => v + 1)
  }, [])

  const handleRedo = useCallback(() => {
    const canvas = canvasRef.current
    const h = historyRef.current
    if (!canvas || !h) return
    const snapshot = h.redo()
    if (!snapshot) return
    void canvas.loadFromJSON(snapshot.json)
    canvas.renderAll()
    setHistoryVersion((v) => v + 1)
    setRedoVersion((v) => v + 1)
  }, [])

  const handleAddText = useCallback(
    (content: string) => {
      const canvas = canvasRef.current
      if (!canvas || !content.trim()) return
      const fontSize = Math.max(24, canvas.height / 12)
      const text = new Text(content, {
        left: canvas.width / 2,
        top: canvas.height / 2,
        fontSize,
        fill: "#ffffff",
        stroke: "#000000",
        strokeWidth: 1,
        textAlign: "center",
        fontFamily: "system-ui, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif",
      })
      canvas.add(text)
      canvas.setActiveObject(text)
      canvas.renderAll()
      commitHistory()
    },
    [commitHistory],
  )

  const handleAddShape = useCallback(
    (shape: "rect" | "circle" | "triangle" | "arrow") => {
      const canvas = canvasRef.current
      if (!canvas) return
      const cx = canvas.width / 2
      const cy = canvas.height / 2
      const size = Math.min(canvas.width, canvas.height) / 4
      let obj: Rect | Circle | Triangle | Line
      switch (shape) {
        case "rect":
          obj = new Rect({ left: cx - size / 2, top: cy - size / 2, width: size, height: size, fill: "#f97316" })
          break
        case "circle":
          obj = new Circle({ left: cx - size / 2, top: cy - size / 2, r: size / 2, fill: "#ef4444" })
          break
        case "triangle":
          obj = new Triangle({ left: cx - size / 2, top: cy - size / 2, width: size, height: size, fill: "#22c55e" })
          break
        case "arrow": {
          const arrow = new Line(
            [cx - size, cy, cx + size, cy],
            {
              stroke: "#ffffff",
              strokeWidth: 6,
              strokeLineCap: "round",
            },
          )
          // 箭头端
          const arrowHead = new Triangle({
            left: cx + size - 12,
            top: cy - 12,
            width: 24,
            height: 24,
            angle: 90,
            fill: "#ffffff",
          })
          obj = arrow
          canvas.add(arrow, arrowHead)
          canvas.renderAll()
          commitHistory()
          return
        }
      }
      canvas.add(obj)
      canvas.setActiveObject(obj)
      canvas.renderAll()
      commitHistory()
    },
    [commitHistory],
  )

  const handleDeleteSelected = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const active = canvas.getActiveObject()
    if (!active) return
    canvas.remove(active)
    canvas.renderAll()
    commitHistory()
  }, [commitHistory])

  const handleAdjustmentChange = useCallback((partial: Partial<ImageFilterAdjustments>) => {
    setAdjustments((prev) => ({ ...prev, ...partial }))
    // 滤镜是"实时预览"：直接以 CSS 滤镜作用于 fabric canvas 底层 canvas
    const canvas = canvasRef.current
    if (!canvas) return
    const el = canvas.getElement()
    el.style.filter = buildFilterCssLocal(partial, {
      brightness: partial.brightness ?? 100,
      contrast: partial.contrast ?? 100,
      saturation: partial.saturation ?? 100,
    })
  }, [])

  /* ---------------- 完成编辑 -> 导出预览 ---------------- */

  const handleFinishEdit = useCallback(async () => {
    const canvas = canvasRef.current
    if (!canvas) return
    setBusy(true)
    try {
      // 先把 CSS 滤镜作用于底层 canvas 元素（导出前烘焙为真实像素）
      // 通过 canvas.toDataURL 会跳过 CSS 滤镜 —— 需要先把底层 canvas 用 filter 重绘
      const rawURL = await bakeFilters(canvas, adjustments)
      setSrcDataURL(rawURL)
      baseImageDataURLRef.current = rawURL
      setStage("export")
    } catch (err) {
      toast({
        title: "生成预览失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      })
    } finally {
      setBusy(false)
    }
  }, [adjustments, toast])

  /* ---------------- 导出下载 ---------------- */

  const handleDownload = useCallback(async () => {
    const canvas = canvasRef.current
    if (!canvas || !srcDataURL) return
    setExporting(true)
    try {
      // 用底层 fabric canvas 作为导出源，可保留透明通道；
      // 但为兼容 CSS 滤镜，用 baseImageDataURL 重新加载一张到 fabric 太绕 —— 直接通过 canvas.toBlob
      // 因为 filters 已在 handleFinishEdit 里烘焙到 srcDataURL；srcDataURL 是"最终产物"
      const finalBlob = await dataURLToBlob(srcDataURL)
      const reencoded = exportFormat === "image/png"
        ? finalBlob
        : await reencodeAsBlob(finalBlob, exportFormat, exportQuality)
      const url = URL.createObjectURL(reencoded)
      const a = document.createElement("a")
      a.href = url
      a.download = `${deriveBaseName(fileName || "image")}.${getExtension(exportFormat)}`
      document.body.appendChild(a)
      a.click()
      a.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
      toast({
        title: "已导出",
        description: `${getExtension(exportFormat).toUpperCase()} · ${(reencoded.size / 1024) | 0} KB`,
      })
    } catch (err) {
      toast({
        title: "导出失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      })
    } finally {
      setExporting(false)
    }
  }, [exportFormat, exportQuality, fileName, srcDataURL, toast])

  const handleBackToCrop = useCallback(() => {
    if (!baseImageDataURLRef.current) return
    setSrcDataURL(baseImageDataURLRef.current)
    resetEditor()
    setPercentCrop({ x: 0, y: 0, width: 1, height: 1, unit: "%" })
    setStage("crop")
  }, [])

  const handleResetAll = useCallback(() => {
    setSrcDataURL(null)
    setFileName("")
    baseImageDataURLRef.current = null
    resetEditor()
    setStage("upload")
  }, [resetEditor])

  /* ---------------- 渲染 ---------------- */

  const history = historyRef.current
  const canUndo = history?.canUndo() ?? false
  const canRedo = history?.canRedo() ?? false

  return (
    <div className="flex h-full min-h-[520px] flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="mr-2 inline-flex items-center gap-1.5 rounded-md bg-foreground/5 px-2 py-1 text-xs text-foreground/60">
          <span className="font-mono">M5</span>
          图片编辑器
        </span>
        <Tabs
          value={stage}
          onValueChange={(v) => {
            if (v === "upload" || v === "crop" || v === "edit" || v === "export") setStage(v)
          }}
        >
          <TabsList>
            <TabsTrigger value="upload">1. 上传</TabsTrigger>
            <TabsTrigger value="crop" disabled={!srcDataURL}>2. 裁剪</TabsTrigger>
            <TabsTrigger value="edit" disabled={!srcDataURL}>3. 编辑</TabsTrigger>
            <TabsTrigger value="export" disabled={stage !== "export"}>4. 导出</TabsTrigger>
          </TabsList>
        </Tabs>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          {stage === "edit" && (
            <>
              <Button variant="ghost" size="sm" disabled={!canUndo} onClick={handleUndo}>
                <Undo2 className="mr-1 h-3.5 w-3.5" /> 撤销
              </Button>
              <Button variant="ghost" size="sm" disabled={!canRedo} onClick={handleRedo}>
                <Redo2 className="mr-1 h-3.5 w-3.5" /> 重做
              </Button>
              <Button variant="outline" size="sm" onClick={handleDeleteSelected}>
                <Trash2 className="mr-1 h-3.5 w-3.5" /> 删除选中
              </Button>
              <Button variant="default" size="sm" onClick={() => void handleFinishEdit()} disabled={busy}>
                <Download className="mr-1 h-3.5 w-3.5" /> 完成编辑
              </Button>
            </>
          )}
          <Button variant="outline" size="sm" disabled={stage === "upload" || busy} onClick={handleResetAll}>
            <RotateCcw className="mr-1 h-3.5 w-3.5" /> 清空
          </Button>
        </div>
      </div>

      <div className="flex-1">
        {stage === "upload" && (
          <Card>
            <CardHeader>
              <h2 className="text-base font-semibold">上传 / 拖拽图片</h2>
              <p className="text-xs text-foreground/60">支持 JPG、PNG、WebP，浏览器本地处理</p>
            </CardHeader>
            <CardContent>
              <div
                {...getRootProps()}
                className={cn(
                  "flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-border/70 bg-card/60 px-6 py-16 text-center transition-colors hover:border-primary/60 hover:bg-accent/40",
                  isDragActive && "border-primary bg-primary/5",
                )}
              >
                <input {...getInputProps()} className="hidden" />
                <UploadCloud className="mb-3 h-10 w-10 text-primary/70" />
                <p className="text-sm font-semibold">拖拽图片到这里，或点击选择文件</p>
                <p className="mt-1 text-xs text-foreground/50">支持 JPG / PNG / WebP</p>
              </div>
            </CardContent>
          </Card>
        )}

        {stage === "crop" && srcDataURL && (
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <div>
                <h2 className="text-base font-semibold">裁剪</h2>
                <p className="text-xs text-foreground/60">调整裁剪区域，支持自由比例与常见固定比例。</p>
              </div>
              <div className="flex items-center gap-2">
                <Select value={cropPresetId} onValueChange={(v) => setCropPresetId(v as CropPresetId)}>
                  <SelectTrigger className="h-8 w-[120px]"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {CROP_PRESETS.map((p) => <SelectItem key={p.id} value={p.id}>{p.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <Button size="sm" onClick={() => void handleApplyCrop()} disabled={busy}>
                  <Scissors className="mr-1 h-3.5 w-3.5" /> 应用裁剪
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="mx-auto max-w-3xl">
                <ReactCrop
                  crop={percentCrop}
                  onChange={(_, percent) => setPercentCrop(percent)}
                  aspect={cropAspect ?? undefined}
                >
                  <img src={srcDataURL} alt="裁剪源图" className="max-h-[520px] w-full object-contain" />
                </ReactCrop>
              </div>
            </CardContent>
          </Card>
        )}

        {stage === "edit" && srcDataURL && (
          <div className="grid gap-4 lg:grid-cols-[1fr_280px]">
            <Card>
              <CardHeader>
                <h2 className="text-base font-semibold">编辑画布</h2>
                <p className="text-xs text-foreground/60">拖拽 / 缩放物体；左侧添加文字与形状；右侧调整滤镜。</p>
              </CardHeader>
              <CardContent>
                <div
                  ref={fabricHostRef}
                  className="mx-auto w-fit overflow-auto rounded-lg border border-dashed border-border/70 bg-[repeating-conic-gradient(#00000008_0%_25%,transparent_0%_50%)] bg-[length:16px_16px] p-2"
                />
              </CardContent>
            </Card>

            <div className="space-y-4">
              <Card>
                <CardHeader><h3 className="text-sm font-semibold">文字</h3></CardHeader>
                <CardContent className="space-y-3">
                  <AddTextForm onAdd={handleAddText} />
                  <AddShapeButtons onAdd={handleAddShape} />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <h3 className="flex items-center justify-between text-sm font-semibold">
                    <span>滤镜</span>
                    <button
                      type="button"
                      className="text-xs font-normal text-primary hover:underline"
                      onClick={() => {
                        setAdjustments({ brightness: 100, contrast: 100, saturation: 100 })
                        const el = canvasRef.current?.getElement()
                        if (el) el.style.filter = "none"
                      }}
                    >
                      重置
                    </button>
                  </h3>
                </CardHeader>
                <CardContent className="space-y-4">
                  <FilterRow label="亮度" value={adjustments.brightness} min={50} max={150} onChange={(v) => handleAdjustmentChange({ brightness: v })} />
                  <FilterRow label="对比度" value={adjustments.contrast} min={50} max={150} onChange={(v) => handleAdjustmentChange({ contrast: v })} />
                  <FilterRow label="饱和度" value={adjustments.saturation} min={0} max={200} onChange={(v) => handleAdjustmentChange({ saturation: v })} />
                </CardContent>
              </Card>
            </div>
          </div>
        )}

        {stage === "export" && srcDataURL && (
          <Card>
            <CardHeader>
              <h2 className="text-base font-semibold">导出</h2>
              <p className="text-xs text-foreground/60">
                源文件：<code>{fileName || "已编辑"}</code>
              </p>
            </CardHeader>
            <CardContent className="grid gap-6 lg:grid-cols-[1fr_280px]">
              <div className="rounded-lg border border-border bg-[repeating-conic-gradient(#00000008_0%_25%,transparent_0%_50%)] bg-[length:16px_16px] p-4">
                <img src={srcDataURL} alt="导出预览" className="max-h-[420px] w-auto" />
              </div>
              <div className="space-y-4">
                <div className="space-y-2">
                  <Label>格式</Label>
                  <Select value={exportFormat} onValueChange={(v) => setExportFormat(v as ImageExportFormat)}>
                    <SelectTrigger className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="image/png">PNG</SelectItem>
                      <SelectItem value="image/jpeg">JPG</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <Label>质量（JPG）</Label>
                  <Slider
                    min={50}
                    max={100}
                    step={1}
                    value={Math.round(exportQuality * 100)}
                    onValueChange={(v) => setExportQuality(v / 100)}
                  />
                  <p className="text-xs text-foreground/50">{(exportQuality * 100) | 0}%</p>
                </div>
                <Button className="w-full" onClick={() => void handleDownload()} disabled={exporting}>
                  {exporting ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Download className="mr-1 h-3.5 w-3.5" />}
                  {exporting ? "导出中…" : `下载 ${getExtension(exportFormat).toUpperCase()}`}
                </Button>
                <Button variant="outline" className="w-full" disabled={busy} onClick={handleBackToCrop}>
                  <Scissors className="mr-1 h-3.5 w-3.5" /> 回到裁剪
                </Button>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 子组件                                                              */
/* ------------------------------------------------------------------ */

function AddTextForm({ onAdd }: { onAdd: (text: string) => void }) {
  const [value, setValue] = useState("Hello")
  return (
    <div className="space-y-2">
      <Label className="text-xs text-foreground/60">添加文字</Label>
      <div className="flex gap-2">
        <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="输入文字…" className="h-8" />
        <Button size="sm" className="shrink-0 px-3" onClick={() => onAdd(value)} disabled={!value.trim()}>
          <Type className="mr-1 h-3.5 w-3.5" /> 添加
        </Button>
      </div>
    </div>
  )
}

function AddShapeButtons({ onAdd }: { onAdd: (shape: "rect" | "circle" | "triangle" | "arrow") => void }) {
  return (
    <div className="space-y-2">
      <Label className="text-xs text-foreground/60">添加形状</Label>
      <div className="grid grid-cols-4 gap-2">
        <Button size="sm" variant="outline" className="flex flex-col items-center gap-1 py-2" onClick={() => onAdd("rect")}>
          <Square className="h-4 w-4" /><span className="text-[10px]">矩形</span>
        </Button>
        <Button size="sm" variant="outline" className="flex flex-col items-center gap-1 py-2" onClick={() => onAdd("circle")}>
          <CircleIcon className="h-4 w-4" /><span className="text-[10px]">圆形</span>
        </Button>
        <Button size="sm" variant="outline" className="flex flex-col items-center gap-1 py-2" onClick={() => onAdd("triangle")}>
          <TriangleIcon className="h-4 w-4" /><span className="text-[10px]">三角</span>
        </Button>
        <Button size="sm" variant="outline" className="flex flex-col items-center gap-1 py-2" onClick={() => onAdd("arrow")}>
          <ArrowUpRight className="h-4 w-4" /><span className="text-[10px]">箭头</span>
        </Button>
      </div>
    </div>
  )
}

function FilterRow(props: { label: string; value: number; min: number; max: number; onChange: (v: number) => void }) {
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <Label className="text-foreground/70">{props.label}</Label>
        <span className="font-mono text-foreground/70">{props.value}%</span>
      </div>
      <Slider min={props.min} max={props.max} step={1} value={props.value} onValueChange={props.onChange} />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 内部工具                                                            */
/* ------------------------------------------------------------------ */

function buildFilterCssLocal(
  _partial: Partial<ImageFilterAdjustments>,
  full: ImageFilterAdjustments,
): string {
  return `brightness(${full.brightness}%) contrast(${full.contrast}%) saturate(${Math.max(0, full.saturation)}%)`
}

/**
 * 把 CSS 滤镜烘焙为真实像素：
 * 1. 用 fabric.canvas.toDataURL 拿到对象 + 背景图
 * 2. 通过原生 canvas 应用 ctx.filter 重绘
 * 3. 返回烘焙后的 PNG dataURL
 */
async function bakeFilters(canvas: CanvasRef, adjustments: ImageFilterAdjustments): Promise<string> {
  const rawURL = canvas.toDataURL({ format: "png", multiplier: 1 })
  const img = await loadImage(rawURL)
  const out = document.createElement("canvas")
  out.width = img.naturalWidth
  out.height = img.naturalHeight
  const ctx = out.getContext("2d")!
  ctx.clearRect(0, 0, out.width, out.height)
  ctx.filter = `brightness(${adjustments.brightness}%) contrast(${adjustments.contrast}%) saturate(${Math.max(0, adjustments.saturation)}%)`
  ctx.drawImage(img, 0, 0)
  ctx.filter = "none"
  return out.toDataURL("image/png")
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = "anonymous"
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error("Failed to load image"))
    img.src = src
  })
}

async function dataURLToBlob(dataURL: string): Promise<Blob> {
  const resp = await fetch(dataURL)
  return resp.blob()
}

async function reencodeAsBlob(blob: Blob, format: ImageExportFormat, quality: number): Promise<Blob> {
  const srcDataURL = await blobToDataURL(blob)
  const img = await loadImage(srcDataURL)
  const canvas = document.createElement("canvas")
  canvas.width = img.naturalWidth
  canvas.height = img.naturalHeight
  const ctx = canvas.getContext("2d")!
  if (format === "image/jpeg") {
    ctx.fillStyle = "#ffffff"
    ctx.fillRect(0, 0, canvas.width, canvas.height)
  }
  ctx.drawImage(img, 0, 0)
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((out) => {
      if (out) resolve(out)
      else reject(new Error("canvas.toBlob returned null"))
    }, format, quality)
  })
}

async function blobToDataURL(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error ?? new Error("FileReader error"))
    reader.readAsDataURL(blob)
  })
}

function deriveBaseName(fileName: string): string {
  const withoutExt = fileName.replace(/\.[^./]+$/, "")
  return withoutExt || "image"
}

function getExtension(fmt: ImageExportFormat): "png" | "jpg" {
  return fmt === "image/png" ? "png" : "jpg"
}
