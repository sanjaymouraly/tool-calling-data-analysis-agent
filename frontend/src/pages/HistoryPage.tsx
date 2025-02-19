import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Clock, History, Search } from 'lucide-react'
import { api } from '../lib/api'
import type { AnalysisResult, HistoryItem } from '../lib/types'
import { formatDate, formatNumber } from '../lib/format'
import { Badge, Card, EmptyState, ErrorBanner } from '../components/ui'
import { Markdown } from '../components/Markdown'
import { ToolTrace } from '../components/ToolTrace'
import { EvidencePanel } from '../components/EvidencePanel'

export default function HistoryPage() {
  const [items, setItems] = useState<HistoryItem[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<AnalysisResult | null>(null)
  const [tab, setTab] = useState('answer')

  const load = useCallback(() => {
    setLoading(true)
    api
      .history(search || undefined)
      .then(setItems)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false))
  }, [search])

  useEffect(() => {
    const timer = window.setTimeout(load, 250)
    return () => window.clearTimeout(timer)
  }, [load])

  const open = async (id: string) => {
    try {
      setSelected(await api.analysis(id))
    } catch (err) {
      setError((err as Error).message)
    }
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Analysis history</h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
            Every analysis is persisted with its plan, tool trace and evidence - it survives a restart.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-900">
          <Search size={15} className="text-slate-400" />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search questions…"
            className="w-56 bg-transparent text-sm outline-none"
            aria-label="Search history"
          />
        </div>
      </header>

      {error ? <ErrorBanner message={error} onRetry={load} /> : null}

      <div className="grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
        <Card title="Analyses" description={`${items.length} record(s)`} bodyClassName="p-0">
          {loading ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2].map((index) => (
                <div key={index} className="h-14 animate-pulse rounded bg-slate-100 dark:bg-slate-800" />
              ))}
            </div>
          ) : items.length === 0 ? (
            <div className="p-4">
              <EmptyState title="No analyses" description="Ask a question in the workspace." icon={<History size={26} />} />
            </div>
          ) : (
            <ul className="max-h-[640px] divide-y divide-slate-100 overflow-y-auto dark:divide-slate-800">
              {items.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => void open(item.id)}
                    className={`w-full px-4 py-3 text-left transition hover:bg-slate-50 dark:hover:bg-slate-800/50 ${
                      selected?.id === item.id ? 'bg-brand-50/70 dark:bg-brand-900/20' : ''
                    }`}
                  >
                    <p className="line-clamp-2 text-sm font-medium">{item.question}</p>
                    <p className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                      <span className="flex items-center gap-1">
                        <Clock size={11} /> {formatDate(item.created_at)}
                      </span>
                      <Badge tone="slate">{item.provider}</Badge>
                      <span>{formatNumber(item.latency_ms, 0)} ms</span>
                      {item.status !== 'completed' ? <Badge tone="amber">{item.status}</Badge> : null}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="min-w-0 space-y-4">
          {!selected ? (
            <EmptyState
              title="Select an analysis"
              description="Pick a record on the left to inspect its answer, tool trace and evidence."
              icon={<History size={30} />}
            />
          ) : (
            <>
              <Card
                title={selected.question}
                description={`${selected.provider}${selected.model ? ` (${selected.model})` : ''} - ${formatDate(selected.created_at)} - ${formatNumber(selected.latency_ms, 0)} ms`}
              >
                <div className="mb-3 flex flex-wrap gap-2">
                  <Badge tone="slate">{selected.tool_trace.length} tool calls</Badge>
                  <Badge tone="emerald">evidence recorded</Badge>
                  <Link to="/workspace" className="link text-xs">
                    Run a new question →
                  </Link>
                </div>
                <Markdown text={selected.answer} />
              </Card>

              <div className="surface overflow-hidden">
                <div className="flex gap-1 border-b border-slate-200 p-1 dark:border-slate-800">
                  {(
                    [
                      ['answer', 'Tool trace'],
                      ['evidence', 'Evidence'],
                    ] as const
                  ).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setTab(id)}
                      className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                        tab === id
                          ? 'bg-brand-600 text-white'
                          : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className="p-4">
                  {tab === 'answer' ? <ToolTrace steps={selected.tool_trace} /> : <EvidencePanel result={selected} />}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
