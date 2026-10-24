import { backendBaseUrl } from "./env"

export interface ApiResponse<T = any> {
  code?: number
  success?: boolean
  msg?: string | null
  message?: string | null
  data: T
}

export class ApiError extends Error {
  constructor(
    public code: number,
    message: string,
    public data?: any
  ) {
    super(message)
    this.name = "ApiError"
  }
}

import { z } from "zod"

export const DEFAULT_FETCH_TIMEOUT_MS = 30_000

export const TIMEOUT_ERROR_MESSAGE = "请求超时，请稍后重试"

/**
 * fetcher 请求配置。`envelope` 控制响应是否为 `{code|success, data}` 包装；
 * false 时直接返回整块 JSON，适配部分后端接口（ip-pool、analytics 等）的非包装形状。
 */
type FetcherOptions = RequestInit & { timeoutMs?: number; envelope?: boolean }

export async function fetcher<T = any>(
  url: string,
  schemaOrOptions?: z.ZodType<any> | FetcherOptions
): Promise<T> {
  // 区分是 schema 还是 options
  const isSchema = schemaOrOptions && 'parse' in schemaOrOptions
  const options = isSchema ? undefined : (schemaOrOptions as FetcherOptions)
  const schema = isSchema ? (schemaOrOptions as z.ZodType<any>) : undefined
  const envelope = options?.envelope ?? true

  try {
    // 默认 30s 超时（可通过 options.timeoutMs 覆盖；传入 signal 时视为调用方自控，不强制超时）
    // 剥掉非 RequestInit 的自定义字段（timeoutMs / envelope），避免透传给 fetch。
    const { timeoutMs = DEFAULT_FETCH_TIMEOUT_MS, envelope: _envelope, ...requestOptions } = options ?? {}
    void _envelope
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    if (timeoutMs > 0 && !requestOptions.signal) {
      timer = setTimeout(() => controller.abort(), timeoutMs)
    }

    const response = await fetch(url, {
      ...requestOptions,
      signal: requestOptions.signal ?? controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...requestOptions?.headers,
      },
    })
    if (timer) clearTimeout(timer)

    if (!response.ok) {
      throw new ApiError(
        response.status,
        `HTTP error! status: ${response.status}`
      )
    }

    const result: ApiResponse<any> = await response.json()

    if (!envelope) {
      // 非包装响应（部分后端接口直返业务对象）：可选 schema 校验后透传
      if (schema) {
        try {
          const validated = schema.parse(result)
          return validated as T
        } catch (error) {
          console.error("Schema validation failed:", error)
          throw new ApiError(400, "Data validation failed", error)
        }
      }
      return result as T
    }

    // 兼容两种响应格式: {code: 200, msg, data} 和 {success: true, data}
    const isSuccess = result.code === 200 || result.success === true
    if (!isSuccess) {
      const errorMsg = result.msg || result.message || "API request failed"
      const errorCode = result.code || (result.success === false ? 400 : 500)
      throw new ApiError(errorCode, errorMsg, result.data)
    }

    // 如果提供了 schema，则验证数据
    if (schema) {
      try {
        const validated = schema.parse(result)
        return validated as T  // 返回整个验证后的对象，而不是只返回data字段
      } catch (error) {
        console.error("Schema validation failed:", error)
        throw new ApiError(400, "Data validation failed", error)
      }
    }

    return result.data
  } catch (error) {
    if (error instanceof ApiError) {
      throw error
    }
    // AbortError 由本 fetcher 的超时控制器触发（DOMException name='AbortError'）；
    // 分类为 408 语义，让上层 UI 显示"请求超时"而不是"服务异常"。
    if (
      (error instanceof Error && error.name === "AbortError") ||
      (typeof DOMException !== "undefined" &&
        error instanceof DOMException &&
        error.name === "AbortError")
    ) {
      throw new ApiError(408, TIMEOUT_ERROR_MESSAGE)
    }
    throw new ApiError(500, error instanceof Error ? error.message : "Unknown error")
  }
}

export async function apiGet<T = any>(url: string): Promise<T> {
  return fetcher<T>(url, { method: "GET" })
}

export async function apiPost<T = any>(
  url: string,
  data?: any
): Promise<T> {
  return fetcher<T>(url, {
    method: "POST",
    body: JSON.stringify(data),
  })
}

export async function apiDelete<T = any>(url: string): Promise<T> {
  return fetcher<T>(url, { method: "DELETE" })
}

export async function apiPut<T = any>(
  url: string,
  data?: any
): Promise<T> {
  return fetcher<T>(url, {
    method: "PUT",
    body: JSON.stringify(data),
  })
}

// 文件上传
export async function uploadFile(
  file: File,
  filename?: string,
  options?: { timeoutMs?: number }
): Promise<string> {
  const formData = new FormData()
  formData.append("file", file)
  if (filename) {
    formData.append("filename", filename)
  }

  const timeoutMs = options?.timeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  let response: Response
  try {
    response = await fetch(`${backendBaseUrl}/uploadSave`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    })
  } catch (error) {
    if (
      (error instanceof Error && error.name === "AbortError") ||
      (typeof DOMException !== "undefined" &&
        error instanceof DOMException &&
        error.name === "AbortError")
    ) {
      throw new ApiError(408, TIMEOUT_ERROR_MESSAGE)
    }
    throw error
  } finally {
    clearTimeout(timer)
  }

  const result: ApiResponse<{ filepath: string }> = await response.json()

  // 兼容两种响应格式
  const isSuccess = result.code === 200 || result.success === true
  if (!isSuccess) {
    const errorMsg = result.msg || result.message || "Upload failed"
    const errorCode = result.code || 400
    throw new ApiError(errorCode, errorMsg)
  }

  return result.data.filepath
}
