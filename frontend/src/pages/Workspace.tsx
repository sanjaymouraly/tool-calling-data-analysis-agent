import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  ClipboardCopy,
  Download,
  Info,
  Send,
  ShieldCheck,
  Sparkles,
  User,
} from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { AnalysisResult, Dataset, ProviderStatus } from '../lib/types'
import { formatNumber } from '../lib/format'
import { Badge, Button, Card, EmptyState, ErrorBanner, InfoBanner, Select, Textarea } from '../components/ui'
import { Markdown } from '../components/Markdown'
import { ChartRenderer } from '../components/ChartRenderer'
import { ToolTrace } from '../components/ToolTrace'
import { EvidencePanel } from '../components/EvidencePanel'
import { useToast } from '../hooks/useToast'

const SUGGESTIONS = [
  'What were monthly sales and growth rates?',
  'Which products generated the highest revenue?',
  'What is the average order value, and how was it calculated?',
  'Compare regional performance this quarter versus last quarter.',
  'Which suppliers have the lowest on-time delivery percentage?',
  'Where are missing values, duplicated records, or unusual changes?',
]

export default function Workspace() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [question, setQuestion] = useState(searchParams.get('q') ?? '')
  const [provider, setProvider] = useState('free')
  const [result, setResult] = useState<AnalysisResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [panel, setPanel] = useState<'answer' | 'trace' | 'evidence'>('answer')
  const [joins, setJoins] = useState<
    { left_dataset_id: string; right_dataset_id: string; left_key: string; right_key: string }[]
  >([])
  const bottomRef = useRef<HTMLDivElement>(null)
  const toast = useToast()

  useEffect(() => {
    api.datasets().then((list) => {
      setDatasets(list)
      const fromUrl = searchParams.get('dataset')
      if (fromUrl && list.some((d) => d.id === fromUrl)) {
        setSelected([fromUrl])
      } else if (list.length) {
        setSelected([list[0].id])
      }
    })
    api.providers().then(setProviders).catch(() => undefined)
  }, [searchParams])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [loading, result])

  const selectedDatasets = useMemo(
    () => datasets.filter((dataset) => selected.includes(dataset.id)),
    [datasets, selected],
  )

  const ask = async (override?: string) => {
    const text = (override ?? question).trim()
    if (text.length < 3) {
      toast.error('Question too short', 'Ask a question of at least 3 characters.')
      return
    }
    if (!selected.length) {
      toast.error('Select a dataset', 'The agent can only read datasets you authorise for this request.')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    setSearchParams({ q: text })
    try {
      const response = await api.ask({
        question: text,
        dataset_ids: selected,
        provider,
        approved_joins: joins,
      })
      setResult(response)
      setPanel('answer')
    } catch (err) {
      const message = err instanceof ApiError ? err.message : 'The analysis failed'
      setError(message)
      toast.error('Analysis failed', message)
    } finally {
      setLoading(false)
    }
  }

  const copyAnswer = async () => {
    if (!result) return
    await navigator.clipboard.writeText(result.answer)
    toast.success('Answer copied to the clipboard')
  }

  const downloadAnswer = () => {
    if (!result) return
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `analysis-${result.id}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const addJoin = () => {
    if (selected.length < 2) {
      toast.error('Select two datasets', 'A join needs a left and a right dataset.')
      return
    }
    const left = selected[0]
    const right = selected[1]
    const leftKey = window.prompt('Left dataset join key (column name)')
    if (!leftKey) return
    const rightKey = window.prompt('Right dataset join key (column name)')
    if (!rightKey) return
    setJoins((current) => [...current, { left_dataset_id: left, right_dataset_id: right, left_key: leftKey, right_key: rightKey }])
    toast.success('Join approved', `${leftKey} = ${rightKey}`)
  }

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0 space-y-4">
        <Card title="Ask the analyst" description="Your question is turned into a validated plan of allowlisted tools.">
          <div className="space-y-4">
            <div>
              <p className="mb-1.5 text-xs font-medium text-slate-700 dark:text-slate-300">
                Authorised datasets <span className="text-slate-400">({selected.length} selected)</span>
              </p>
              <div className="flex flex-wrap gap-2">
                {datasets.map((dataset) => {
                  const active = selected.includes(dataset.id)
                  return (
                    <button
                      key={dataset.id}
                      type="button"
                      aria-pressed={active}
                      onClick={() =>
                        setSelected((current) =>
                          current.includes(dataset.id)
                            ? current.filter((id) => id !== dataset.id)
                            : [...current, dataset.id],
                        )
                      }
                      className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                        active
                          ? 'border-brand-500 bg-brand-50 text-brand-800 dark:border-brand-700 dark:bg-brand-900/40 dark:text-brand-100'
                          : 'border-slate-300 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300'
                      }`}
                    >
                      {dataset.name}
                      <span className="ml-1.5 text-[10px] opacity-70">{formatNumber(dataset.row_count, 0)}</span>
                    </button>
                  )
                })}
                {datasets.length === 0 ? (
                  <span className="text-xs text-amber-600">No datasets found - import one first.</span>
                ) : null}
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-700 dark:text-slate-300">
                  AI provider
                </label>
                <Select value={provider} onChange={(event) => setProvider(event.target.value)}>
                  {providers.map((item) => (
                    <option key={item.provider} value={item.provider}>
                      {item.label}
                      {item.has_key ? '' : item.requires_key ? ' (key required)' : ''}
                    </option>
                  ))}
                </Select>
                <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                  {provider === 'free'
                    ? 'Deterministic guided mode - fully offline, no data leaves this machine.'
                    : providers.find((item) => item.provider === provider)?.notes}
                </p>
              </div>
              <div>
                <span className="mb-1.5 block text-xs font-medium text-slate-700 dark:text-slate-300">
                  Approved joins
                </span>
                <div className="flex flex-wrap items-center gap-2">
                  <Button variant="secondary" onClick={addJoin} className="text-xs">
                    Approve a join key
                  </Button>
                  {joins.map((join, index) => (
                    <span
                      key={index}
                      className="chip bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200"
                    >
                      {join.left_key} = {join.right_key}
                    </span>
                  ))}
                  {joins.length === 0 ? (
                    <span className="text-[11px] text-slate-500">None - joins are blocked without approval.</span>
                  ) : null}
                </div>
              </div>
            </div>

            <div>
              <label htmlFor="question" className="mb-1.5 block text-xs font-medium text-slate-700 dark:text-slate-300">
                Question
              </label>
              <div className="flex flex-col gap-2 sm:flex-row">
                <Textarea
                  id="question"
                  rows={2}
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) void ask()
                  }}
                  placeholder="e.g. What were monthly sales and growth rates?"
                />
                <Button
                  variant="primary"
                  onClick={() => void ask()}
                  loading={loading}
                  icon={<Send size={15} />}
                  className="sm:self-end"
                >
                  {loading ? 'Analysing' : 'Ask'}
                </Button>
              </div>
              <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                Press <span className="kbd">Ctrl</span> + <span className="kbd">Enter</span> to run.
              </p>
            </div>

            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => {
                    setQuestion(suggestion)
                    void ask(suggestion)
                  }}
                  className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] text-slate-600 transition hover:border-brand-300 hover:bg-brand-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        </Card>

        {error ? <ErrorBanner message={error} /> : null}

        {loading ? (
          <Card>
            <div className="flex items-center gap-3 py-8">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
              <div>
                <p className="text-sm font-medium">Running the analysis workflow</p>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Inspect → plan → validate → execute → verify → answer
                </p>
              </div>
            </div>
          </Card>
        ) : null}

        {result ? (
          <>
            <Card
              title="Evidence-backed answer"
              description={`${result.provider}${result.model ? ` (${result.model})` : ''} - ${formatNumber(result.latency_ms, 0)} ms`}
              actions={
                <div className="flex gap-2">
                  <Button variant="ghost" onClick={copyAnswer} icon={<ClipboardCopy size={14} />} className="text-xs">
                    Copy
                  </Button>
                  <Button variant="ghost" onClick={downloadAnswer} icon={<Download size={14} />} className="text-xs">
                    Export
                  </Button>
                </div>
              }
            >
              <div className="mb-3 flex flex-wrap gap-2">
                {result.status === 'completed' ? (
                  <Badge tone="emerald">
                    <CheckCircle2 size={12} /> completed
                  </Badge>
                ) : result.status === 'needs_clarification' ? (
                  <Badge tone="amber">
                    <AlertTriangle size={12} /> needs clarification
                  </Badge>
                ) : (
                  <Badge tone="rose">
                    <AlertTriangle size={12} /> failed
                  </Badge>
                )}
                <Badge tone="slate">{result.tool_trace.length} tool calls</Badge>
                {result.verification?.all_verified === false ? (
                  <Badge tone="amber">unverified numeric claims flagged</Badge>
                ) : null}
              </div>

              {result.clarification ? (
                <div className="mb-3">
                  <InfoBanner title="Clarification needed" tone="warning">
                    {result.clarification}
                  </InfoBanner>
                </div>
              ) : null}

              <Markdown text={result.answer} />

              {result.verification?.unverified_claims?.length ? (
                <div className="mt-4">
                  <InfoBanner title="Some numbers could not be verified" tone="warning">
                    The model narrative mentioned{' '}
                    {result.verification.unverified_claims.map((claim) => claim.text).join(', ')}, which could not
                    be matched against the tool output. Treat those figures as unconfirmed.
                  </InfoBanner>
                </div>
              ) : null}
            </Card>

            {result.charts.length ? (
              <Card title="Visualisations" description="Declarative chart specifications - no code is executed.">
                <div className="space-y-6">
                  {result.charts.map((chart, index) => (
                    <div key={index}>
                      <ChartRenderer spec={chart} />
                    </div>
                  ))}
                </div>
              </Card>
            ) : null}

            <div className="surface overflow-hidden">
              <div className="flex gap-1 border-b border-slate-200 p-1 dark:border-slate-800">
                {(
                  [
                    ['answer', 'Answer'],
                    ['trace', `Tool trace (${result.tool_trace.length})`],
                    ['evidence', 'How this was calculated'],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setPanel(id)}
                    className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                      panel === id
                        ? 'bg-brand-600 text-white'
                        : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="p-4">
                {panel === 'answer' ? (
                  <div className="space-y-3 text-xs text-slate-600 dark:text-slate-400">
                    <p className="flex items-start gap-2">
                      <ShieldCheck size={14} className="mt-0.5 shrink-0 text-emerald-600" />
                      {result.evidence.note}
                    </p>
                    <p className="flex items-start gap-2">
                      <Info size={14} className="mt-0.5 shrink-0 text-sky-600" />
                      {result.verification?.note}
                    </p>
                    {result.plan?.clarification ? (
                      <p className="flex items-start gap-2">
                        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-600" />
                        {result.plan.clarification}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {panel === 'trace' ? <ToolTrace steps={result.tool_trace} /> : null}
                {panel === 'evidence' ? <EvidencePanel result={result} /> : null}
              </div>
            </div>
          </>
        ) : null}

        {!result && !loading ? (
          <EmptyState
            title="No analysis yet"
            description="Pick a dataset, ask a question and the agent will inspect the schema, build a validated plan and run the analysis."
            icon={<Sparkles size={30} />}
          />
        ) : null}

        <div ref={bottomRef} />
      </div>

      <aside className="space-y-4">
        <Card title="Workflow" description="Every step is recorded and reproducible.">
          <ol className="space-y-2 text-xs">
            {[
              ['Inspect', 'authorised schema, types and date ranges'],
              ['Plan', 'structured tool plan, validated against the allowlist'],
              ['Execute', 'schema-checked, dataset-scoped, time-boxed calls'],
              ['Verify', 'numeric claims matched against tool output'],
              ['Answer', 'grounded narrative plus the evidence panel'],
            ].map(([title, description], index) => (
              <li key={title} className="flex gap-2.5">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-bold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  {index + 1}
                </span>
                <span>
                  <span className="font-semibold text-slate-800 dark:text-slate-100">{title}</span>{' '}
                  <span className="text-slate-500 dark:text-slate-400">{description}</span>
                </span>
              </li>
            ))}
          </ol>
        </Card>

        <Card title="Authorised data" description="Only these datasets can be read in this request.">
          {selectedDatasets.length === 0 ? (
            <p className="text-xs text-slate-500">No dataset selected.</p>
          ) : (
            <ul className="space-y-2 text-xs">
              {selectedDatasets.map((dataset) => (
                <li key={dataset.id} className="rounded-lg bg-slate-50 p-2 dark:bg-slate-800/60">
                  <p className="font-medium">{dataset.name}</p>
                  <p className="text-[11px] text-slate-500 dark:text-slate-400">
                    {formatNumber(dataset.row_count, 0)} rows - {dataset.column_count} columns - sha256{' '}
                    {dataset.file_hash.slice(0, 8)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Safety" description="What the agent cannot do.">
          <ul className="space-y-1.5 text-xs text-slate-600 dark:text-slate-400">
            {[
              'No Python, shell commands or SQL from the model',
              'No reading or writing arbitrary files',
              'No cross-dataset access outside the authorised set',
              'No joins without an approved key',
              'Cell content is data, never instructions',
            ].map((item) => (
              <li key={item} className="flex items-start gap-2">
                <ShieldCheck size={13} className="mt-0.5 shrink-0 text-emerald-600" />
                {item}
              </li>
            ))}
          </ul>
        </Card>

        <Card title="Conversation">
          <div className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-400">
            <Bot size={14} className="mt-0.5 shrink-0 text-brand-600" />
            <p>
              Each question is stored with its plan, tool trace and evidence, so you can revisit or export the
              exact reasoning later.
            </p>
          </div>
          <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
            <User size={13} />
            {result ? 'Last answer is shown above.' : 'No answer in this session yet.'}
          </div>
        </Card>
      </aside>
    </div>
  )
}
