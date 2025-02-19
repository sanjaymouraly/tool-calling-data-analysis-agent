import type {
  AnalysisResult,
  AppConfig,
  ChartSpec,
  Dataset,
  DatasetSchema,
  HistoryItem,
  ProviderStatus,
  QualityReport,
  ToolDefinition,
} from './types'

const BASE_URL = (import.meta.env?.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export class ApiError extends Error {
  status: number
  details: unknown
  constructor(message: string, status: number, details?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.details = details
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      headers: init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch (error) {
    throw new ApiError(
      `Could not reach the backend (${(error as Error).message}). Is the API running on port 8000?`,
      0,
    )
  }

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  if (!response.ok) {
    const body = payload as { error?: { message?: string; details?: unknown }; detail?: string } | null
    const message =
      body?.error?.message ??
      body?.detail ??
      (typeof payload === 'string' ? payload : `Request failed with status ${response.status}`)
    throw new ApiError(message, response.status, body?.error?.details)
  }
  return payload as T
}

export const api = {
  health: () => request<{ status: string; version: string }>('/api/health'),
  info: () => request<Record<string, unknown>>('/api/info'),
  config: () => request<AppConfig>('/api/settings/config'),

  datasets: () => request<Dataset[]>('/api/datasets'),
  dataset: (id: string) => request<Dataset>(`/api/datasets/${id}`),
  schema: (id: string) => request<DatasetSchema>(`/api/datasets/${id}/schema`),
  preview: (id: string, limit = 50, offset = 0) =>
    request<{ rows: Record<string, unknown>[]; columns: string[]; total_rows: number }>(
      `/api/datasets/${id}/preview?limit=${limit}&offset=${offset}`,
    ),
  quality: (id: string) => request<QualityReport>(`/api/datasets/${id}/quality`),
  deleteDataset: (id: string) => request<{ ok: boolean }>(`/api/datasets/${id}`, { method: 'DELETE' }),
  approveDataset: (id: string, approved: boolean) =>
    request<{ id: string; is_approved: boolean }>(`/api/datasets/${id}/approve?approved=${approved}`, {
      method: 'POST',
    }),

  async upload(file: File, sheetName?: string, description?: string, onProgress?: (pct: number) => void) {
    const form = new FormData()
    form.append('file', file)
    if (sheetName) form.append('sheet_name', sheetName)
    if (description) form.append('description', description)

    // XHR gives us real upload progress events.
    return new Promise<{ id: string; name: string; row_count: number; column_count: number }>(
      (resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.open('POST', `${BASE_URL}/api/datasets/upload`)
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable && onProgress) {
            onProgress(Math.round((event.loaded / event.total) * 100))
          }
        }
        xhr.onload = () => {
          try {
            const body = JSON.parse(xhr.responseText || '{}')
            if (xhr.status >= 200 && xhr.status < 300) resolve(body)
            else reject(new ApiError(body?.error?.message ?? body?.detail ?? 'Upload failed', xhr.status))
          } catch {
            reject(new ApiError('Upload failed: invalid response', xhr.status))
          }
        }
        xhr.onerror = () => reject(new ApiError('Upload failed: network error', 0))
        xhr.send(form)
      },
    )
  },

  ask: (payload: {
    question: string
    dataset_ids: string[]
    provider: string
    conversation_id?: string | null
    approved_joins?: { left_dataset_id: string; right_dataset_id: string; left_key: string; right_key: string }[]
  }) => request<AnalysisResult>('/api/analysis/query', { method: 'POST', body: JSON.stringify(payload) }),

  history: (search?: string) =>
    request<HistoryItem[]>(`/api/analysis/history${search ? `?search=${encodeURIComponent(search)}` : ''}`),
  analysis: (id: string) => request<AnalysisResult>(`/api/analysis/history/${id}`),
  conversations: () => request<{ id: string; title: string; message_count: number }[]>('/api/analysis/conversations'),

  tools: () => request<ToolDefinition[]>('/api/analysis/tools'),
  toolCatalogue: () => request<{ count: number; tools: ToolDefinition[] }>('/api/analysis/tools/catalogue'),
  runTool: (tool: string, args: Record<string, unknown>, datasetIds: string[]) =>
    request<{ data: Record<string, unknown>; evidence: Record<string, unknown> }>('/api/tools/run', {
      method: 'POST',
      body: JSON.stringify({ tool, arguments: args, dataset_ids: datasetIds }),
    }),

  providers: () => request<ProviderStatus[]>('/api/settings/providers'),
  testProvider: (payload: { provider: string; base_url?: string; api_key?: string; model?: string }) =>
    request<Record<string, unknown>>('/api/settings/providers/test', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  saveProvider: (payload: {
    provider: string
    base_url?: string
    api_key?: string
    model?: string
    enabled?: boolean
  }) =>
    request<Record<string, unknown>>('/api/settings/providers', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  providerModels: (provider: string) =>
    request<{ models: string[]; count: number }>(`/api/settings/providers/${provider}/models`),
  usage: () => request<Record<string, unknown>>('/api/settings/usage'),

  reports: () => request<{ id: string; title: string; created_at: string }[]>('/api/reports'),
  createReport: (payload: { title: string; analysis_id?: string; chart?: ChartSpec; notes?: string }) =>
    request<{ id: string }>('/api/reports', { method: 'POST', body: JSON.stringify(payload) }),
  deleteReport: (id: string) => request<{ ok: boolean }>(`/api/reports/${id}`, { method: 'DELETE' }),
}

export const exportUrl = {
  dataset: (id: string, format: 'csv' | 'xlsx' | 'json') => `${BASE_URL}/api/datasets/${id}/export?format=${format}`,
  report: (id: string, format: 'pdf' | 'csv' | 'json') => `${BASE_URL}/api/reports/${id}/export?format=${format}`,
}
