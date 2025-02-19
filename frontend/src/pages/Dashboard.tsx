import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  BarChart3,
  Database,
  FileSpreadsheet,
  MessageSquareText,
  ShieldCheck,
  Sparkles,
  Upload,
  Wrench,
} from 'lucide-react'
import { api } from '../lib/api'
import type { AppConfig, Dataset, HistoryItem } from '../lib/types'
import { formatNumber, relativeTime } from '../lib/format'
import { Badge, Card, EmptyState, ErrorBanner, Skeleton } from '../components/ui'

const DEMO_QUESTIONS = [
  'What were monthly sales and growth rates?',
  'Which products generated the highest revenue?',
  'What is the average order value, and how was it calculated?',
  'Compare regional performance this quarter versus last quarter.',
  'Which suppliers have the lowest on-time delivery percentage?',
  'Where are missing values, duplicated records, or unusual changes?',
]

export default function Dashboard() {
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [history, setHistory] = useState<HistoryItem[]>([])
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    setError(null)
    Promise.all([api.datasets(), api.history(), api.config()])
      .then(([datasetList, historyList, appConfig]) => {
        setDatasets(datasetList)
        setHistory(historyList)
        setConfig(appConfig)
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [])

  const stats = useMemo(() => {
    const rows = datasets.reduce((total, dataset) => total + dataset.row_count, 0)
    const columns = datasets.reduce((total, dataset) => total + dataset.column_count, 0)
    return { datasets: datasets.length, rows, columns }
  }, [datasets])

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Overview</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600 dark:text-slate-400">
            Upload a spreadsheet, ask a business question and get a reproducible, evidence-cited answer.
            Every calculation runs through a fixed library of validated tools - the model never executes code.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/datasets" className="btn-secondary">
            <Upload size={15} /> Upload data
          </Link>
          <Link to="/workspace" className="btn-primary">
            <MessageSquareText size={15} /> Open workspace
          </Link>
        </div>
      </header>

      {error ? <ErrorBanner message={error} onRetry={load} /> : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[
          { label: 'Datasets', value: stats.datasets, icon: Database, tone: 'text-brand-600' },
          { label: 'Rows available', value: stats.rows, icon: FileSpreadsheet, tone: 'text-emerald-600' },
          { label: 'Analyses run', value: history.length, icon: BarChart3, tone: 'text-violet-600' },
          {
            label: 'Allowlisted tools',
            value: config?.kpi_catalogue ? 19 : 19,
            icon: ShieldCheck,
            tone: 'text-amber-600',
          },
        ].map((stat) => (
          <Card key={stat.label}>
            <div className="flex items-center gap-3">
              <div className={`rounded-lg bg-slate-100 p-2 dark:bg-slate-800 ${stat.tone}`}>
                <stat.icon size={18} />
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">{stat.label}</p>
                {loading ? (
                  <Skeleton className="mt-1 h-7 w-16" />
                ) : (
                  <p className="text-2xl font-bold tabular-nums">{formatNumber(stat.value, 0)}</p>
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Ready-to-run questions"
          description="These work immediately - even with no AI API key, using the deterministic guided mode."
        >
          <div className="grid gap-2 sm:grid-cols-2">
            {DEMO_QUESTIONS.map((question) => (
              <Link
                key={question}
                to={`/workspace?q=${encodeURIComponent(question)}`}
                className="group flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm text-slate-700 transition hover:border-brand-300 hover:bg-brand-50/50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:border-brand-700"
              >
                <Sparkles size={15} className="mt-0.5 shrink-0 text-brand-500" />
                <span className="flex-1">{question}</span>
                <ArrowRight
                  size={14}
                  className="mt-0.5 shrink-0 text-slate-400 opacity-0 transition group-hover:opacity-100"
                />
              </Link>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
            <Badge tone="brand">free mode</Badge>
            <Badge tone="slate">no API key required</Badge>
            <Badge tone="slate">deterministic plan</Badge>
            <Badge tone="emerald">cited evidence</Badge>
          </div>
        </Card>

        <Card title="Recent analyses" description="Persisted across restarts.">
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          ) : history.length === 0 ? (
            <EmptyState
              title="No analyses yet"
              description="Ask your first question in the workspace and it will appear here."
              icon={<MessageSquareText size={26} />}
            />
          ) : (
            <ul className="space-y-2">
              {history.slice(0, 6).map((item) => (
                <li key={item.id}>
                  <Link
                    to="/history"
                    className="block rounded-lg border border-slate-200 px-3 py-2 transition hover:border-brand-300 dark:border-slate-800"
                  >
                    <p className="truncate text-sm font-medium">{item.question}</p>
                    <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                      {relativeTime(item.created_at)} · {item.provider} · {formatNumber(item.latency_ms, 0)} ms
                    </p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
          {history.length ? (
            <Link to="/history" className="link mt-3 inline-block text-xs">
              View all history →
            </Link>
          ) : null}
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card
          title="Datasets"
          description="Files you have imported, with content hashes for reproducibility."
          actions={
            <Link to="/datasets" className="btn-secondary text-xs">
              Manage
            </Link>
          }
        >
          {loading ? (
            <div className="space-y-2">
              <Skeleton className="h-10 w-full" />
              <Skeleton className="h-10 w-full" />
            </div>
          ) : datasets.length === 0 ? (
            <EmptyState
              title="No datasets yet"
              description="Upload a CSV, XLSX or Parquet file to get started."
              icon={<Database size={26} />}
              action={
                <Link to="/datasets" className="btn-primary text-xs">
                  <Upload size={14} /> Upload a file
                </Link>
              }
            />
          ) : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {datasets.slice(0, 6).map((dataset) => (
                <li key={dataset.id} className="flex items-center gap-3 py-2">
                  <div className="min-w-0 flex-1">
                    <Link to={`/datasets/${dataset.id}`} className="truncate text-sm font-medium hover:underline">
                      {dataset.name}
                    </Link>
                    <p className="text-[11px] text-slate-500 dark:text-slate-400">
                      {formatNumber(dataset.row_count, 0)} rows · {dataset.column_count} columns ·{' '}
                      {dataset.file_type}
                    </p>
                  </div>
                  {dataset.is_demo ? <Badge tone="violet">demo</Badge> : null}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="How the agent works" description="A controlled, inspectable pipeline.">
          <ol className="space-y-2.5 text-sm">
            {[
              ['Inspect', 'Schema, types, roles and date ranges are read from the authorised datasets.'],
              ['Plan', 'A structured plan of allowlisted tool calls is produced and validated.'],
              ['Execute', 'Each call is schema-checked, dataset-scoped, time-boxed and size-limited.'],
              ['Verify', 'Numeric claims are checked against the tool output before display.'],
              ['Cite', 'Dataset hash, row counts, filters and formulas are stored with the answer.'],
            ].map(([title, description], index) => (
              <li key={title} className="flex gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-[11px] font-bold text-brand-700 dark:bg-brand-900/40 dark:text-brand-200">
                  {index + 1}
                </span>
                <span>
                  <span className="font-medium">{title}</span>{' '}
                  <span className="text-slate-600 dark:text-slate-400">{description}</span>
                </span>
              </li>
            ))}
          </ol>
          <div className="mt-4 flex gap-2">
            <Link to="/builder" className="btn-secondary text-xs">
              <Wrench size={14} /> Visual query builder
            </Link>
            <Link to="/settings" className="btn-secondary text-xs">
              Configure an AI provider
            </Link>
          </div>
        </Card>
      </div>
    </div>
  )
}
