import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, Download, FileSpreadsheet, Search, ShieldCheck } from 'lucide-react'
import { api, exportUrl } from '../lib/api'
import type { DatasetSchema, QualityReport } from '../lib/types'
import { formatDate, formatNumber, shortHash } from '../lib/format'
import { Badge, Card, EmptyState, ErrorBanner, Spinner, Tabs } from '../components/ui'

const TYPE_TONES: Record<string, string> = {
  numeric: 'bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-200',
  currency: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
  date: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200',
  datetime: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-200',
  boolean: 'bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-200',
  string: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  mixed_numeric: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
}

export default function DatasetDetail() {
  const { id } = useParams<{ id: string }>()
  const [schema, setSchema] = useState<DatasetSchema | null>(null)
  const [quality, setQuality] = useState<QualityReport | null>(null)
  const [preview, setPreview] = useState<{
    rows: Record<string, unknown>[]
    columns: string[]
    total_rows: number
  } | null>(null)
  const [meta, setMeta] = useState<{ name: string; file_hash: string; created_at: string; version: number } | null>(
    null,
  )
  const [tab, setTab] = useState('preview')
  const [filter, setFilter] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    setError(null)
    Promise.all([api.schema(id), api.quality(id), api.preview(id, 50), api.dataset(id)])
      .then(([schemaData, qualityData, previewData, dataset]) => {
        setSchema(schemaData)
        setQuality(qualityData)
        setPreview(previewData)
        setMeta(dataset)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [id])

  const columns = useMemo(
    () =>
      (schema?.columns ?? []).filter((column) =>
        filter ? column.name.toLowerCase().includes(filter.toLowerCase()) : true,
      ),
    [schema, filter],
  )

  if (loading) return <Spinner label="Loading dataset..." />
  if (error) return <ErrorBanner message={error} />
  if (!schema || !meta) return <EmptyState title="Dataset not found" />

  const score = quality?.score ?? 0
  const scoreTone = score >= 80 ? 'emerald' : score >= 60 ? 'amber' : 'rose'

  return (
    <div className="space-y-5">
      <Link to="/datasets" className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800 dark:hover:text-slate-200">
        <ArrowLeft size={14} /> Back to datasets
      </Link>

      <header className="surface p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="flex items-center gap-2 text-xl font-bold">
              <FileSpreadsheet size={20} className="text-brand-600" />
              {meta.name}
            </h1>
            <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
              {meta.name ? '' : null}
              {formatNumber(schema.row_count, 0)} rows - {schema.column_count} columns - v{meta.version} -
              imported {formatDate(meta.created_at)}
            </p>
            <p className="mt-1 font-mono text-[11px] text-slate-500 dark:text-slate-400">
              sha256 {shortHash(meta.file_hash)}...
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <a href={exportUrl.dataset(id!, 'csv')} className="btn-secondary text-xs" download>
              <Download size={14} /> CSV
            </a>
            <a href={exportUrl.dataset(id!, 'xlsx')} className="btn-secondary text-xs" download>
              <Download size={14} /> XLSX
            </a>
            <Link to={`/workspace?dataset=${id}`} className="btn-primary text-xs">
              Ask a question
            </Link>
          </div>
        </div>

        {schema.warnings.length ? (
          <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">
            <p className="flex items-center gap-1.5 font-semibold">
              <AlertTriangle size={14} /> Data quality warnings
            </p>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
              {schema.warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </header>

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: 'preview', label: 'Preview', count: preview?.rows.length },
          { id: 'schema', label: 'Schema', count: schema.columns.length },
          { id: 'quality', label: 'Data quality', count: quality?.issues.length },
        ]}
      />

      {tab === 'preview' && preview ? (
        <Card
          title={`First ${preview.rows.length} of ${formatNumber(preview.total_rows, 0)} rows`}
          description="Bounded preview - the full dataset stays on the server."
          bodyClassName="p-0"
        >
          <div className="overflow-auto max-h-[560px]">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-100 dark:bg-slate-800">
                <tr>
                  {preview.columns.map((column) => (
                    <th
                      key={column}
                      className="whitespace-nowrap border-b border-slate-200 px-3 py-2 text-left font-semibold dark:border-slate-700"
                    >
                      {column}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((row, index) => (
                  <tr
                    key={index}
                    className="border-b border-slate-100 hover:bg-slate-50 dark:border-slate-800/70 dark:hover:bg-slate-800/40"
                  >
                    {preview.columns.map((column) => {
                      const value = row[column]
                      const isFormula = typeof value === 'string' && /^[=+\-@]/.test(value)
                      return (
                        <td
                          key={column}
                          className="max-w-[220px] truncate px-3 py-1.5 text-slate-700 dark:text-slate-300"
                          title={value === null || value === undefined ? '' : String(value)}
                        >
                          {value === null || value === undefined ? (
                            <span className="text-slate-300 dark:text-slate-600">null</span>
                          ) : isFormula ? (
                            <span className="text-rose-600 dark:text-rose-400" title="Sanitised on export">
                              {String(value)}
                            </span>
                          ) : (
                            String(value)
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {tab === 'schema' ? (
        <Card
          title="Inferred schema"
          description="Types are inferred from the data and the reason is shown for each column."
          actions={
            <div className="flex items-center gap-2">
              <Search size={14} className="text-slate-400" />
              <input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Filter columns"
                className="w-40 rounded-md border border-slate-300 bg-white px-2 py-1 text-xs outline-none focus:border-brand-500 dark:border-slate-700 dark:bg-slate-900"
                aria-label="Filter columns"
              />
            </div>
          }
          bodyClassName="p-0"
        >
          <div className="overflow-auto">
            <table className="w-full text-xs">
              <thead className="bg-slate-50 dark:bg-slate-800/60">
                <tr>
                  {['Column', 'Type', 'Role', 'Missing', 'Unique', 'Sample'].map((header) => (
                    <th key={header} className="px-3 py-2 text-left font-semibold text-slate-600 dark:text-slate-300">
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {columns.map((column) => (
                  <tr
                    key={column.name}
                    className="border-t border-slate-100 dark:border-slate-800"
                  >
                    <td className="px-3 py-2 font-medium text-slate-800 dark:text-slate-100">
                      {column.name}
                      {column.dtype ? (
                        <span className="ml-2 font-mono text-[10px] text-slate-400">{column.dtype}</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2">
                      <span className={`chip ${TYPE_TONES[column.inferred_type] ?? TYPE_TONES.string}`}>
                        {column.inferred_type}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {column.role_hint ? (
                        <Badge tone="brand">{column.role_hint}</Badge>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {formatNumber(column.missing_pct ?? 0, 1)}%
                    </td>
                    <td className="px-3 py-2 tabular-nums">
                      {column.unique_count === null || column.unique_count === undefined
                        ? 'many'
                        : formatNumber(column.unique_count, 0)}
                    </td>
                    <td className="max-w-[260px] truncate px-3 py-2 text-slate-500 dark:text-slate-400">
                      {(column.sample_values ?? []).map((value) => String(value)).join(', ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {tab === 'quality' && quality ? (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Quality score">
            <div className="flex items-center gap-4">
              <div
                className={`flex h-20 w-20 items-center justify-center rounded-full text-2xl font-bold text-white ${
                  scoreTone === 'emerald'
                    ? 'bg-emerald-500'
                    : scoreTone === 'amber'
                      ? 'bg-amber-500'
                      : 'bg-rose-500'
                }`}
              >
                {Math.round(score)}
              </div>
              <div className="text-xs text-slate-600 dark:text-slate-400">
                <p className="font-semibold text-slate-800 dark:text-slate-100">out of 100</p>
                <p className="mt-1">
                  {formatNumber(quality.duplicates.count, 0)} duplicate rows (
                  {formatNumber(quality.duplicates.pct, 2)}%)
                </p>
              </div>
            </div>
          </Card>

          <Card title="Missing values">
            {Object.entries(quality.missing_values).filter(([, value]) => value.missing > 0).length === 0 ? (
              <p className="text-sm text-emerald-600">No missing values.</p>
            ) : (
              <ul className="space-y-2">
                {Object.entries(quality.missing_values)
                  .filter(([, value]) => value.missing > 0)
                  .sort((a, b) => b[1].pct - a[1].pct)
                  .slice(0, 8)
                  .map(([column, value]) => (
                    <li key={column}>
                      <div className="flex items-center justify-between text-xs">
                        <span className="truncate font-medium">{column}</span>
                        <span className="tabular-nums text-slate-500">
                          {value.missing} ({value.pct}%)
                        </span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                        <div
                          className="h-full rounded-full bg-amber-500"
                          style={{ width: `${Math.min(100, value.pct)}%` }}
                        />
                      </div>
                    </li>
                  ))}
              </ul>
            )}
          </Card>

          <Card title="Outliers (IQR)">
            {Object.keys(quality.outliers).length === 0 ? (
              <p className="text-sm text-slate-500">No statistical outliers detected.</p>
            ) : (
              <ul className="space-y-2 text-xs">
                {Object.entries(quality.outliers).map(([column, value]) => (
                  <li key={column} className="rounded-lg bg-slate-50 p-2 dark:bg-slate-800/60">
                    <p className="font-medium">{column}</p>
                    <p className="text-slate-500 dark:text-slate-400">
                      {value.count} values ({value.pct}%) outside [{formatNumber(value.lower)},{' '}
                      {formatNumber(value.upper)}]
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="Warnings and issues" className="lg:col-span-3">
            <ul className="space-y-1.5 text-xs">
              {quality.warnings.map((warning) => (
                <li key={warning} className="flex items-start gap-2 text-slate-700 dark:text-slate-300">
                  <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-500" />
                  {warning}
                </li>
              ))}
              {quality.issues.map((issue, index) => (
                <li
                  key={`${issue.type}-${index}`}
                  className="flex items-start gap-2 text-slate-700 dark:text-slate-300"
                >
                  <Badge tone={issue.severity === 'high' ? 'rose' : issue.severity === 'medium' ? 'amber' : 'slate'}>
                    {issue.severity}
                  </Badge>
                  <span>
                    {issue.detail}
                    {issue.column ? ` (${issue.column})` : ''}
                  </span>
                </li>
              ))}
            </ul>
          </Card>

          <Card title="Security notes" className="lg:col-span-3">
            <p className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-400">
              <ShieldCheck size={14} className="mt-0.5 shrink-0 text-emerald-600" />
              Column names, file names and cell values are treated as data, never as instructions. Values that
              look like spreadsheet formulas are neutralised on export.
            </p>
          </Card>
        </div>
      ) : null}
    </div>
  )
}
