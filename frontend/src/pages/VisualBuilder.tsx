import { useEffect, useMemo, useState } from 'react'
import { BarChart3, Filter, Play, Sigma, Table2 } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { Dataset, DatasetSchema, ToolDefinition } from '../lib/types'
import { formatNumber } from '../lib/format'
import { Badge, Button, Card, EmptyState, ErrorBanner, Field, Input, Select } from '../components/ui'
import { useToast } from '../hooks/useToast'

type Mode = 'aggregate' | 'rank' | 'kpi' | 'filter'

const MODES: { id: Mode; label: string; icon: typeof Sigma; description: string }[] = [
  { id: 'aggregate', label: 'Aggregate', icon: Sigma, description: 'Sum, average or count a measure' },
  { id: 'rank', label: 'Rank', icon: BarChart3, description: 'Top or bottom categories by a measure' },
  { id: 'kpi', label: 'KPI', icon: Table2, description: 'A supported business KPI' },
  { id: 'filter', label: 'Filter', icon: Filter, description: 'Rows matching a predicate' },
]

export default function VisualBuilder() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [schema, setSchema] = useState<DatasetSchema | null>(null)
  const [tools, setTools] = useState<ToolDefinition[]>([])
  const [kpis, setKpis] = useState<{ name: string; label: string; required_roles: string[] }[]>([])
  const [datasetId, setDatasetId] = useState('')
  const [mode, setMode] = useState<Mode>('aggregate')
  const [measure, setMeasure] = useState('')
  const [groupBy, setGroupBy] = useState('')
  const [agg, setAgg] = useState('sum')
  const [kpi, setKpi] = useState('')
  const [limit, setLimit] = useState('10')
  const [output, setOutput] = useState<Record<string, unknown> | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  useEffect(() => {
    api.datasets().then((list) => {
      setDatasets(list)
      if (list.length) setDatasetId(list[0].id)
    })
    api.toolCatalogue().then((result) => setTools(result.tools)).catch(() => undefined)
    api.config().then((config) => setKpis(config.kpi_catalogue)).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!datasetId) return
    api.schema(datasetId).then(setSchema).catch(() => setSchema(null))
  }, [datasetId])

  const numericColumns = useMemo(
    () => (schema?.columns ?? []).filter((column) => ['numeric', 'currency', 'mixed_numeric'].includes(column.inferred_type)),
    [schema],
  )
  const dimensionColumns = useMemo(
    () => (schema?.columns ?? []).filter((column) => !['numeric', 'currency', 'mixed_numeric'].includes(column.inferred_type)),
    [schema],
  )

  useEffect(() => {
    if (!measure && numericColumns.length) setMeasure(numericColumns[0].name)
  }, [numericColumns, measure])

  const run = async () => {
    if (!datasetId) return
    setBusy(true)
    setError(null)
    setOutput(null)
    try {
      let tool = 'aggregate_metrics'
      let args: Record<string, unknown> = {}
      if (mode === 'aggregate') {
        // Without a dimension the aggregation runs over the whole dataset.
        tool = groupBy ? 'group_by' : 'aggregate_metrics'
        args = {
          dataset_id: datasetId,
          ...(groupBy ? { by: [groupBy], limit: Number(limit) || 50 } : {}),
          metrics: [{ column: measure, agg, alias: `${measure}_${agg}` }],
        }
      } else if (mode === 'rank') {
        tool = 'rank_categories'
        args = {
          dataset_id: datasetId,
          category_column: groupBy,
          metric_column: measure,
          agg,
          top_n: Number(limit) || 10,
        }
      } else if (mode === 'kpi') {
        tool = 'compute_kpi'
        const params: Record<string, string> = {}
        const mapping: Record<string, string> = {
          revenue_column: measure,
          cost_column: numericColumns.find((c) => c.role_hint === 'cost')?.name ?? '',
          order_id_column: schema?.columns.find((c) => c.role_hint === 'order_id')?.name ?? '',
        }
        Object.entries(mapping).forEach(([key, value]) => {
          if (value) params[key] = value
        })
        args = { dataset_id: datasetId, kpi, params }
      } else {
        tool = 'apply_filters'
        args = {
          dataset_id: datasetId,
          filters: [{ column: groupBy, op: 'not_null', value: null }],
          limit: Number(limit) || 50,
        }
      }
      const result = await api.runTool(tool, args, [datasetId])
      setOutput(result.data)
      toast.success('Query executed', `${tool} returned ${formatNumber(result.data.row_count ?? 0, 0)} row(s).`)
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'The tool call failed'
      setError(message)
      toast.error('Tool call failed', message)
    } finally {
      setBusy(false)
    }
  }

  const rows = useMemo(() => {
    if (!output) return []
    const candidates = output.results ?? output.ranked ?? output.rows ?? output.groups ?? []
    return Array.isArray(candidates) ? (candidates as Record<string, unknown>[]) : []
  }, [output])

  if (!datasets.length) {
    return (
      <EmptyState
        title="No datasets available"
        description="Import a spreadsheet before using the visual query builder."
        icon={<Table2 size={30} />}
      />
    )
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Visual query builder</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600 dark:text-slate-400">
          Build a deterministic analysis without an AI provider. The builder calls exactly the same
          allowlisted tools as the agent, so the evidence guarantees are identical.
        </p>
      </header>

      <div className="grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
        <Card title="Query" description="Pick a dataset and the operation.">
          <div className="space-y-4">
            <Field label="Dataset" htmlFor="vb-dataset">
              <Select id="vb-dataset" value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
                {datasets.map((dataset) => (
                  <option key={dataset.id} value={dataset.id}>
                    {dataset.name} ({formatNumber(dataset.row_count, 0)} rows)
                  </option>
                ))}
              </Select>
            </Field>

            <div>
              <p className="mb-1.5 text-xs font-medium text-slate-700 dark:text-slate-300">Operation</p>
              <div className="grid grid-cols-2 gap-2">
                {MODES.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setMode(item.id)}
                    aria-pressed={mode === item.id}
                    className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-xs transition ${
                      mode === item.id
                        ? 'border-brand-500 bg-brand-50 text-brand-800 dark:border-brand-700 dark:bg-brand-900/40 dark:text-brand-100'
                        : 'border-slate-200 text-slate-600 hover:bg-slate-50 dark:border-slate-800 dark:text-slate-300 dark:hover:bg-slate-800'
                    }`}
                  >
                    <item.icon size={14} />
                    {item.label}
                  </button>
                ))}
              </div>
            </div>

            {mode === 'kpi' ? (
              <Field label="KPI" htmlFor="vb-kpi" hint="Only KPIs whose source columns exist can be computed.">
                <Select id="vb-kpi" value={kpi} onChange={(event) => setKpi(event.target.value)}>
                  <option value="">Select a KPI…</option>
                  {kpis.map((definition) => (
                    <option key={definition.name} value={definition.name}>
                      {definition.label}
                    </option>
                  ))}
                </Select>
              </Field>
            ) : (
              <>
                <Field label="Measure (numeric column)" htmlFor="vb-measure">
                  <Select id="vb-measure" value={measure} onChange={(event) => setMeasure(event.target.value)}>
                    {numericColumns.map((column) => (
                      <option key={column.name} value={column.name}>
                        {column.name}
                      </option>
                    ))}
                  </Select>
                </Field>
                {mode === 'rank' || mode === 'aggregate' ? (
                  <Field label="Group by" htmlFor="vb-group" hint="Optional dimension, e.g. Region.">
                    <Select id="vb-group" value={groupBy} onChange={(event) => setGroupBy(event.target.value)}>
                      <option value="">No grouping</option>
                      {dimensionColumns.map((column) => (
                        <option key={column.name} value={column.name}>
                          {column.name}
                        </option>
                      ))}
                    </Select>
                  </Field>
                ) : null}
                {mode !== 'filter' ? (
                  <Field label="Aggregation" htmlFor="vb-agg">
                    <Select id="vb-agg" value={agg} onChange={(event) => setAgg(event.target.value)}>
                      {['sum', 'mean', 'median', 'min', 'max', 'count', 'count_distinct', 'std'].map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </Select>
                  </Field>
                ) : null}
              </>
            )}

            <Field label="Row limit" htmlFor="vb-limit">
              <Input
                id="vb-limit"
                type="number"
                min={1}
                max={2000}
                value={limit}
                onChange={(event) => setLimit(event.target.value)}
              />
            </Field>

            <Button variant="primary" onClick={() => void run()} loading={busy} icon={<Play size={15} />} className="w-full">
              Run query
            </Button>
          </div>
        </Card>

        <div className="min-w-0 space-y-4">
          {error ? <ErrorBanner message={error} /> : null}

          <Card
            title="Result"
            description={output ? `${rows.length} row(s) returned` : 'Run a query to see the result.'}
            bodyClassName="p-0"
          >
            {rows.length ? (
              <div className="overflow-auto max-h-[520px]">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-slate-100 dark:bg-slate-800">
                    <tr>
                      {Object.keys(rows[0]).map((key) => (
                        <th key={key} className="whitespace-nowrap px-3 py-2 text-left font-semibold">
                          {key}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row, index) => (
                      <tr key={index} className="border-t border-slate-100 dark:border-slate-800">
                        {Object.keys(row).map((key) => (
                          <td key={key} className="whitespace-nowrap px-3 py-1.5 tabular-nums">
                            {typeof row[key] === 'number'
                              ? formatNumber(row[key])
                              : String(row[key] ?? '—')}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : output ? (
              <div className="p-5">
                <pre className="overflow-auto rounded bg-slate-50 p-3 font-mono text-[11px] dark:bg-slate-950/60">
                  {JSON.stringify(output, null, 2)}
                </pre>
              </div>
            ) : (
              <div className="p-5">
                <p className="text-sm text-slate-500">Nothing executed yet.</p>
              </div>
            )}
          </Card>

          <Card title="Available tools" description="The complete, finite library - the model cannot add to it.">
            <div className="flex flex-wrap gap-1.5">
              {tools.map((tool) => (
                <Badge key={tool.name} tone="slate" title={tool.description}>
                  {tool.name}
                </Badge>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
