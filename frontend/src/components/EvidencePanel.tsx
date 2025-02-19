import { CheckCircle2, FileText, Fingerprint, Info, ListChecks, Sigma } from 'lucide-react'
import type { AnalysisResult } from '../lib/types'
import { formatDate, formatNumber, shortHash } from '../lib/format'
import { Badge, Disclosure } from './ui'

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-slate-100 py-1.5 last:border-0 dark:border-slate-800">
      <span className="shrink-0 text-[11px] uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-right text-xs text-slate-800 dark:text-slate-200">{value}</span>
    </div>
  )
}

export function EvidencePanel({ result }: { result: AnalysisResult }) {
  const evidence = result.evidence
  const how = result.how_calculated

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Fingerprint size={15} className="text-brand-600" />
          Source data
        </h3>
        <div className="space-y-3">
          {evidence.datasets.map((dataset) => (
            <div key={dataset.id} className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900/70">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold">{dataset.name}</span>
                {dataset.is_demo ? <Badge tone="violet">demo</Badge> : null}
                <Badge tone="slate">v{dataset.version}</Badge>
                {dataset.sheet ? <Badge tone="slate">sheet {dataset.sheet}</Badge> : null}
              </div>
              <div className="mt-2">
                <Row label="Rows" value={formatNumber(dataset.row_count, 0)} />
                <Row label="Columns" value={formatNumber(dataset.column_count, 0)} />
                <Row label="Dataset id" value={<code className="font-mono text-[11px]">{dataset.id}</code>} />
                <Row label="SHA-256" value={<code className="font-mono text-[11px]">{shortHash(dataset.file_hash)}…</code>} />
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Sigma size={15} className="text-brand-600" />
          Definitions &amp; assumptions
        </h3>
        <dl className="space-y-2">
          {Object.entries(how.definitions ?? {}).map(([name, description]) => (
            <div key={name}>
              <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                {name.replace(/_/g, ' ')}
              </dt>
              <dd className="text-xs leading-relaxed text-slate-700 dark:text-slate-300">{description}</dd>
            </div>
          ))}
        </dl>
        <div className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-800">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Assumptions
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-slate-700 dark:text-slate-300">
            {how.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
          <p className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Exclusions
          </p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs text-slate-700 dark:text-slate-300">
            {how.exclusions.map((exclusion) => (
              <li key={exclusion}>{exclusion}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <ListChecks size={15} className="text-brand-600" />
          Per-step reproducibility
        </h3>
        <div className="space-y-3">
          {how.steps.map((step, index) => (
            <Disclosure
              key={`${step.tool}-${index}`}
              defaultOpen={index === 0}
              title={
                <span className="flex items-center gap-2 text-xs">
                  <span className="font-mono">{step.tool}</span>
                  <Badge tone={step.status === 'success' ? 'emerald' : 'rose'}>{step.status}</Badge>
                </span>
              }
            >
              <div className="rounded bg-slate-50 p-3 dark:bg-slate-950/50">
                {step.formula ? (
                  <p className="mb-2 font-mono text-[11px] text-slate-800 dark:text-slate-200">
                    {step.formula}
                  </p>
                ) : null}
                <Row label="Rows in" value={formatNumber(step.row_counts?.dataset_rows, 0)} />
                <Row label="Rows out" value={formatNumber(step.row_counts?.result_rows, 0)} />
                <Row label="Filters" value={step.filters?.length ? JSON.stringify(step.filters) : 'none'} />
                <Row label="Elapsed" value={step.elapsed_ms !== undefined ? `${step.elapsed_ms} ms` : '—'} />
              </div>
            </Disclosure>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <FileText size={15} className="text-brand-600" />
          Run metadata
        </h3>
        <Row label="Provider" value={result.provider} />
        <Row label="Model" value={result.model ?? 'n/a (deterministic)'} />
        <Row label="Latency" value={`${formatNumber(result.latency_ms, 0)} ms`} />
        <Row label="Workflow" value={(result.states ?? []).join(' → ')} />
        <Row label="Tools run" value={String(result.tool_trace?.length ?? 0)} />
        <Row label="Generated" value={formatDate(evidence.generated_at)} />
        <p className="mt-3 flex items-start gap-2 text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">
          {result.verification?.all_verified ? (
            <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-emerald-600" />
          ) : (
            <Info size={13} className="mt-0.5 shrink-0 text-amber-600" />
          )}
          {result.verification?.note ?? evidence.note}
        </p>
      </section>
    </div>
  )
}
