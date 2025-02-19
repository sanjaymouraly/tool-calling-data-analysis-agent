import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Database, FileSpreadsheet, Search, Trash2, Upload, X } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { Dataset } from '../lib/types'
import { formatBytes, formatNumber, relativeTime } from '../lib/format'
import { Badge, Button, Card, EmptyState, ErrorBanner } from '../components/ui'
import { useToast } from '../hooks/useToast'

const ACCEPT = '.csv,.xlsx,.xlsm,.parquet'

export default function Datasets() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const toast = useToast()

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    api
      .datasets()
      .then(setDatasets)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const upload = async (file: File) => {
    if (!/\.(csv|xlsx|xlsm|parquet)$/i.test(file.name)) {
      toast.error('Unsupported file type', 'Allowed formats: CSV, XLSX, XLSM and Parquet.')
      return
    }
    setUploading(true)
    setProgress(0)
    try {
      const result = await api.upload(file, undefined, undefined, setProgress)
      toast.success(
        'Dataset imported',
        `${result.name}: ${formatNumber(result.row_count, 0)} rows x ${result.column_count} columns.`,
      )
      load()
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'Upload failed'
      toast.error('Upload failed', message)
      setError(message)
    } finally {
      setUploading(false)
      setProgress(0)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const remove = async (dataset: Dataset) => {
    if (!window.confirm(`Delete "${dataset.name}"? The stored file is removed as well.`)) return
    try {
      await api.deleteDataset(dataset.id)
      toast.success('Dataset deleted', dataset.name)
      load()
    } catch (err) {
      toast.error('Delete failed', (err as Error).message)
    }
  }

  const filtered = datasets.filter((dataset) => {
    if (!search) return true
    const needle = search.toLowerCase()
    return (
      dataset.name.toLowerCase().includes(needle) ||
      dataset.original_filename.toLowerCase().includes(needle) ||
      dataset.description?.toLowerCase().includes(needle)
    )
  })

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dataset manager</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Import CSV, XLSX (multi-sheet) or Parquet files. Originals are preserved with a SHA-256 hash and
            lineage.
          </p>
        </div>
        <Button
          variant="primary"
          onClick={() => inputRef.current?.click()}
          loading={uploading}
          icon={<Upload size={15} />}
        >
          {uploading ? `Uploading ${progress}%` : 'Upload file'}
        </Button>
      </header>

      {error ? <ErrorBanner message={error} onRetry={load} /> : null}

      <div
        onDragOver={(event) => {
          event.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault()
          setDragging(false)
          const file = event.dataTransfer.files?.[0]
          if (file) void upload(file)
        }}
        className={`surface border-dashed p-6 text-center transition ${
          dragging ? 'border-brand-400 bg-brand-50/50 dark:bg-brand-900/20' : ''
        }`}
      >
        <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-slate-500 dark:bg-slate-800">
          <Upload size={19} />
        </div>
        <p className="mt-3 text-sm font-medium">
          Drop a spreadsheet here, or{' '}
          <button type="button" onClick={() => inputRef.current?.click()} className="link">
            browse your files
          </button>
        </p>
        <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          CSV - XLSX - XLSM - Parquet. Files are validated, hashed and stored locally.
        </p>
        {uploading ? (
          <div className="mx-auto mt-4 h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
            <div
              className="h-full rounded-full bg-brand-600 transition-all"
              style={{ width: `${Math.max(progress, 5)}%` }}
            />
          </div>
        ) : null}
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) void upload(file)
          }}
        />
      </div>

      <div className="surface flex items-center gap-2 px-4 py-2.5">
        <Search size={16} className="text-slate-400" />
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search datasets..."
          className="flex-1 bg-transparent text-sm outline-none"
          aria-label="Search datasets"
        />
        {search ? (
          <button type="button" onClick={() => setSearch('')} aria-label="Clear search">
            <X size={14} className="text-slate-400 hover:text-slate-600" />
          </button>
        ) : null}
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {filtered.length} of {datasets.length}
        </span>
      </div>

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((index) => (
            <div key={index} className="surface h-48 animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          title={datasets.length ? 'No matching datasets' : 'No datasets yet'}
          description={
            datasets.length
              ? 'Try a different search term.'
              : 'Upload a spreadsheet above, or start the backend which seeds the synthetic demo datasets automatically.'
          }
          icon={<Database size={30} />}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {filtered.map((dataset) => (
            <Card key={dataset.id} className="flex flex-col">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <Link
                    to={`/datasets/${dataset.id}`}
                    className="block truncate text-sm font-semibold hover:underline"
                  >
                    {dataset.name}
                  </Link>
                  <p className="mt-0.5 truncate text-[11px] text-slate-500 dark:text-slate-400">
                    {dataset.original_filename}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {dataset.is_demo ? <Badge tone="violet">demo</Badge> : null}
                  <button
                    type="button"
                    onClick={() => remove(dataset)}
                    className="rounded p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950"
                    aria-label={`Delete ${dataset.name}`}
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>

              <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
                {[
                  ['Rows', formatNumber(dataset.row_count, 0)],
                  ['Columns', formatNumber(dataset.column_count, 0)],
                  ['Size', formatBytes(dataset.size_bytes)],
                ].map(([label, value]) => (
                  <div key={label} className="rounded-lg bg-slate-50 py-2 dark:bg-slate-800/60">
                    <dt className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">
                      {label}
                    </dt>
                    <dd className="text-sm font-semibold tabular-nums">{value}</dd>
                  </div>
                ))}
              </dl>

              <div className="mt-3 space-y-1 text-[11px] text-slate-500 dark:text-slate-400">
                <p>
                  <span className="font-medium text-slate-600 dark:text-slate-300">sha256</span>{' '}
                  <code className="font-mono">{dataset.file_hash.slice(0, 16)}</code>
                </p>
                <p>
                  <span className="font-medium text-slate-600 dark:text-slate-300">imported</span>{' '}
                  {relativeTime(dataset.created_at)} - v{dataset.version}
                  {dataset.sheet_name ? ` - sheet ${dataset.sheet_name}` : ''}
                </p>
              </div>

              <div className="mt-4 flex gap-2 pt-1">
                <Link to={`/datasets/${dataset.id}`} className="btn-secondary flex-1 text-xs">
                  <FileSpreadsheet size={14} /> Inspect
                </Link>
                <Link to={`/workspace?dataset=${dataset.id}`} className="btn-primary flex-1 text-xs">
                  Ask a question
                </Link>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
