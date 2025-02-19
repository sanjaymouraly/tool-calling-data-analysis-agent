import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Clock, XCircle } from 'lucide-react'
import clsx from 'clsx'
import type { ToolTraceStep } from '../lib/types'

function StatusIcon({ status }: { status: ToolTraceStep['status'] }) {
  if (status === 'success') return <CheckCircle2 size={14} className="text-emerald-600" />
  if (status === 'cancelled') return <Clock size={14} className="text-amber-600" />
  return <XCircle size={14} className="text-rose-600" />
}

export function ToolTrace({ steps }: { steps: ToolTraceStep[] }) {
  const [open, setOpen] = useState<Record<number, boolean>>({})

  if (!steps.length) {
    return <p className="text-xs text-slate-500">No tool was executed for this request.</p>
  }

  return (
    <ol className="space-y-2">
      {steps.map((step) => {
        const expanded = open[step.step] ?? false
        const elapsed = step.output?._meta?.elapsed_ms
        return (
          <li
            key={`${step.step}-${step.tool}`}
            className={clsx(
              'rounded-lg border',
              step.status === 'success'
                ? 'border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900'
                : 'border-rose-200 bg-rose-50/60 dark:border-rose-900 dark:bg-rose-950/30',
            )}
          >
            <button
              type="button"
              onClick={() => setOpen((current) => ({ ...current, [step.step]: !expanded }))}
              aria-expanded={expanded}
              className="flex w-full items-center gap-2 px-3 py-2 text-left"
            >
              {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              <StatusIcon status={step.status} />
              <span className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-100">
                {step.tool}
              </span>
              <span className="chip bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                step {step.step}
              </span>
              {elapsed !== undefined ? (
                <span className="ml-auto text-[11px] text-slate-500 dark:text-slate-400">{elapsed} ms</span>
              ) : null}
            </button>
            {step.reason ? (
              <p className="px-3 pb-1 text-[11px] text-slate-500 dark:text-slate-400">Why: {step.reason}</p>
            ) : null}
            {step.error ? (
              <p className="px-3 pb-2 text-[11px] text-rose-700 dark:text-rose-300">{step.error}</p>
            ) : null}
            {expanded ? (
              <div className="grid gap-2 border-t border-slate-200 p-3 md:grid-cols-2 dark:border-slate-800">
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    Arguments
                  </p>
                  <pre className="max-h-64 overflow-auto rounded bg-slate-50 p-2 font-mono text-[11px] leading-relaxed text-slate-700 dark:bg-slate-950/70 dark:text-slate-300">
                    {JSON.stringify(step.input ?? {}, null, 2)}
                  </pre>
                </div>
                <div>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
                    {step.status === 'success' ? 'Result' : 'Error'}
                  </p>
                  <pre className="max-h-64 overflow-auto rounded bg-slate-50 p-2 font-mono text-[11px] leading-relaxed text-slate-700 dark:bg-slate-950/70 dark:text-slate-300">
                    {step.status === 'success'
                      ? JSON.stringify(step.output?.data ?? {}, null, 2).slice(0, 4000)
                      : step.error}
                  </pre>
                </div>
                {step.warnings?.length ? (
                  <div className="md:col-span-2">
                    {step.warnings.map((warning) => (
                      <p
                        key={warning}
                        className="mt-1 flex items-start gap-1.5 text-[11px] text-amber-700 dark:text-amber-300"
                      >
                        <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                        {warning}
                      </p>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}
