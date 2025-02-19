import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Download, FileText, Trash2 } from 'lucide-react'
import { api, exportUrl } from '../lib/api'
import { formatDate } from '../lib/format'
import { Badge, Card, EmptyState, ErrorBanner } from '../components/ui'
import { useToast } from '../hooks/useToast'

interface Report {
  id: string
  title: string
  analysis_id?: string | null
  dataset_id?: string | null
  chart?: { title?: string; chart_type?: string; data?: Record<string, unknown>[] }
  notes?: string | null
  created_at: string
}

export default function Reports() {
  const [reports, setReports] = useState<Report[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const toast = useToast()

  const load = useCallback(() => {
    setLoading(true)
    api
      .reports()
      .then((items) => setReports(items as unknown as Report[]))
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const remove = async (report: Report) => {
    if (!window.confirm(`Delete report "${report.title}"?`)) return
    try {
      await api.deleteReport(report.id)
      toast.success('Report deleted', report.title)
      load()
    } catch (err) {
      toast.error('Delete failed', (err as Error).message)
    }
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Saved reports</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Pinned analyses with their chart and provenance. Export as PDF, CSV or JSON.
          </p>
        </div>
        <Link to="/history" className="btn-secondary text-sm">
          Browse the full history
        </Link>
      </header>

      {error ? <ErrorBanner message={error} onRetry={load} /> : null}

      {loading ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((index) => (
            <div key={index} className="surface h-40 animate-pulse" />
          ))}
        </div>
      ) : reports.length === 0 ? (
        <EmptyState
          title="No saved reports"
          description="Run an analysis in the workspace and save it to build a report library."
          icon={<FileText size={30} />}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {reports.map((report) => (
            <Card key={report.id}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold">{report.title}</p>
                  <p className="mt-0.5 text-[11px] text-slate-500 dark:text-slate-400">
                    {formatDate(report.created_at)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => remove(report)}
                  className="rounded p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950"
                  aria-label={`Delete ${report.title}`}
                >
                  <Trash2 size={14} />
                </button>
              </div>

              <div className="mt-3 flex flex-wrap gap-1.5">
                {report.chart?.chart_type ? <Badge tone="brand">{report.chart.chart_type}</Badge> : null}
                {report.chart?.data ? <Badge tone="slate">{report.chart.data.length} points</Badge> : null}
                {report.analysis_id ? <Badge tone="emerald">linked analysis</Badge> : null}
              </div>

              {report.notes ? (
                <p className="mt-3 line-clamp-3 text-xs text-slate-600 dark:text-slate-400">{report.notes}</p>
              ) : null}

              <div className="mt-4 flex gap-2">
                <a href={exportUrl.report(report.id, 'pdf')} className="btn-secondary flex-1 text-xs" download>
                  <Download size={13} /> PDF
                </a>
                <a href={exportUrl.report(report.id, 'csv')} className="btn-secondary flex-1 text-xs" download>
                  <Download size={13} /> CSV
                </a>
                <a href={exportUrl.report(report.id, 'json')} className="btn-secondary flex-1 text-xs" download>
                  <Download size={13} /> JSON
                </a>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card title="How reports are created" description="Reports keep the full provenance chain.">
        <ul className="list-disc space-y-1 pl-5 text-xs text-slate-600 dark:text-slate-400">
          <li>Open an analysis in the workspace and use "Save as report".</li>
          <li>The report stores the chart specification, the question, the tool trace and the dataset hashes.</li>
          <li>PDF exports include the question, the answer and the provenance block.</li>
        </ul>
      </Card>
    </div>
  )
}
