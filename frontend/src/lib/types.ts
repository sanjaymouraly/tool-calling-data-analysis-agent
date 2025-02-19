export interface Dataset {
  id: string
  name: string
  original_filename: string
  file_type: string
  sheet_name?: string | null
  row_count: number
  column_count: number
  size_bytes: number
  currency: string
  is_demo: boolean
  is_approved: boolean
  description?: string | null
  lineage_id: string
  version: number
  created_at: string
  updated_at: string
  file_hash: string
}

export interface ColumnSchema {
  name: string
  position?: number
  dtype?: string
  inferred_type: string
  inference_reason?: string
  nullable?: boolean
  missing_count?: number
  missing_pct?: number
  unique_count?: number | null
  sample_values?: unknown[]
  stats?: Record<string, unknown>
  currency?: string | null
  role_hint?: string | null
}

export interface DatasetSchema {
  dataset_id: string
  dataset_name: string
  row_count: number
  column_count: number
  columns: ColumnSchema[]
  warnings: string[]
  currency: string
}

export interface QualityReport {
  dataset_id: string
  score: number
  row_count: number
  column_count: number
  missing_values: Record<string, { missing: number; total: number; pct: number }>
  duplicates: { count: number; pct: number }
  outliers: Record<string, { count: number; pct: number; lower: number; upper: number }>
  type_issues: { column?: string; detail?: string }[]
  constant_columns: string[]
  issues: { type: string; severity: string; column?: string | null; detail: string }[]
  warnings: string[]
}

export interface ChartSpec {
  chart_type: string
  title: string
  x_key: string
  y_keys: string[]
  data: Record<string, unknown>[]
  x_label?: string
  y_label?: string
  currency?: string
  note?: string
}

export interface ToolTraceStep {
  step: number
  tool: string
  input?: Record<string, unknown>
  reason?: string
  status: 'success' | 'error' | 'cancelled'
  output?: {
    data?: Record<string, unknown>
    evidence?: Record<string, unknown>
    _meta?: { tool: string; elapsed_ms: number; round: number }
  }
  evidence?: Record<string, unknown>
  error?: string
  error_code?: string
  warnings?: string[]
}

export interface Evidence {
  datasets: {
    id: string
    name: string
    version: number
    row_count: number
    column_count: number
    sheet?: string | null
    file_hash: string
    artifact_hash?: string
    currency?: string
    is_demo?: boolean
  }[]
  tool_evidence: { tool: string; status: string; evidence: Record<string, unknown> }[]
  verifiable: boolean
  note: string
  generated_at?: string
  notes?: string[]
}

export interface HowCalculated {
  plan: { steps: { tool: string; input: Record<string, unknown>; reason: string }[]; clarification?: string }
  steps: {
    step?: number
    tool: string
    status: string
    reason?: string
    input?: Record<string, unknown>
    evidence?: Record<string, unknown>
    row_counts?: Record<string, number | null | undefined>
    filters?: unknown[]
    periods?: Record<string, unknown>
    formula?: string
    elapsed_ms?: number
    warnings?: string[]
  }[]
  datasets: Evidence['datasets']
  provider: string
  model?: string | null
  definitions: Record<string, string>
  assumptions: string[]
  exclusions: string[]
  execution_metadata: Record<string, unknown>
}

export interface AnalysisResult {
  id: string
  conversation_id?: string | null
  created_at?: string
  question: string
  answer: string
  status: 'completed' | 'failed' | 'needs_clarification'
  plan: HowCalculated['plan']
  tool_trace: ToolTraceStep[]
  evidence: Evidence
  how_calculated: HowCalculated
  charts: ChartSpec[]
  usage: Record<string, unknown>
  verification: {
    all_verified?: boolean
    total_claims?: number
    unverified_claims?: { text: string; value: number }[]
    note?: string
  }
  clarification?: string | null
  provider: string
  model?: string | null
  latency_ms: number
  states: string[]
}

export interface HistoryItem {
  id: string
  question: string
  provider: string
  model?: string | null
  status: string
  latency_ms: number
  created_at: string
  dataset_ids: string[]
}

export interface ProviderStatus {
  provider: string
  label: string
  requires_key: boolean
  base_url: string
  model: string
  has_key: boolean
  masked_key?: string | null
  key_hint?: string | null
  supports_native_tools: boolean
  supports_model_listing: boolean
  notes: string
  source: string
}

export interface KpiDefinition {
  name: string
  label: string
  description: string
  formula: string
  unit: string
  required_roles: string[]
  optional_roles: string[]
  currency_aware: boolean
  notes: string
}

export interface AppConfig {
  app_name: string
  app_slug: string
  version: string
  environment: string
  max_upload_size_mb: number
  max_tool_rounds: number
  max_tool_result_rows: number
  tool_timeout_seconds: number
  request_cost_budget_usd: number
  request_token_budget: number
  default_provider: string
  kpi_catalogue: KpiDefinition[]
}

export interface ToolDefinition {
  name: string
  description: string
  category: string
  input_schema: Record<string, unknown>
  output: string
}
