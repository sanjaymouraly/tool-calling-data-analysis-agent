import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react'
import clsx from 'clsx'

/* -------------------------------------------------------------------------- */
/* Card                                                                      */
/* -------------------------------------------------------------------------- */

export function Card({
  title,
  description,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: ReactNode
  description?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  className?: string
  bodyClassName?: string
}) {
  return (
    <section className={clsx('surface overflow-hidden', className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
          <div className="min-w-0">
            {title ? <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h2> : null}
            {description ? (
              <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{description}</p>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </header>
      )}
      <div className={clsx('p-5', bodyClassName)}>{children}</div>
    </section>
  )
}

/* -------------------------------------------------------------------------- */
/* Badge                                                                     */
/* -------------------------------------------------------------------------- */

export type BadgeTone = 'slate' | 'brand' | 'emerald' | 'amber' | 'rose' | 'violet' | 'sky'

const BADGE_TONES: Record<BadgeTone, string> = {
  slate: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300',
  brand: 'bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200',
  emerald: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200',
  amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200',
  rose: 'bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-200',
  violet: 'bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-200',
  sky: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200',
}

export function Badge({
  tone = 'slate',
  children,
  className,
  title,
}: {
  tone?: BadgeTone
  children: ReactNode
  className?: string
  title?: string
}) {
  return (
    <span className={clsx('chip', BADGE_TONES[tone], className)} title={title}>
      {children}
    </span>
  )
}

/* -------------------------------------------------------------------------- */
/* Button                                                                    */
/* -------------------------------------------------------------------------- */

export function Button({
  variant = 'primary',
  loading = false,
  icon,
  children,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  loading?: boolean
  icon?: ReactNode
}) {
  const variantClass = {
    primary: 'btn-primary',
    secondary: 'btn-secondary',
    ghost: 'btn-ghost',
    danger: 'btn-danger',
  }[variant]

  return (
    <button
      type="button"
      className={clsx(variantClass, className)}
      disabled={props.disabled || loading}
      {...props}
    >
      {loading ? <Loader2 size={15} className="animate-spin" /> : icon}
      {children}
    </button>
  )
}

/* -------------------------------------------------------------------------- */
/* Form controls                                                             */
/* -------------------------------------------------------------------------- */

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: ReactNode
  hint?: ReactNode
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-slate-700 dark:text-slate-300">
        {label}
      </label>
      {children}
      {hint ? <p className="text-[11px] leading-relaxed text-slate-500 dark:text-slate-400">{hint}</p> : null}
    </div>
  )
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={clsx('field', className)} {...props} />
}

export function Select({ className, children, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={clsx('field', className)} {...props}>
      {children}
    </select>
  )
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={clsx('field resize-y', className)} {...props} />
}

/* -------------------------------------------------------------------------- */
/* States                                                                    */
/* -------------------------------------------------------------------------- */

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500" role="status">
      <Loader2 size={16} className="animate-spin" />
      <span>{label}</span>
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={clsx('animate-pulse rounded bg-slate-200 dark:bg-slate-800', className)} />
}

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string
  description?: ReactNode
  icon?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50/60 px-6 py-12 text-center dark:border-slate-700 dark:bg-slate-900/40">
      {icon ? <div className="mb-3 text-slate-400">{icon}</div> : null}
      <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</p>
      {description ? (
        <p className="mt-1 max-w-md text-xs leading-relaxed text-slate-500 dark:text-slate-400">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  )
}

export function ErrorBanner({
  title = 'Something went wrong',
  message,
  onRetry,
}: {
  title?: string
  message: string
  onRetry?: () => void
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-lg border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-900 dark:border-rose-900 dark:bg-rose-950/60 dark:text-rose-200"
      role="alert"
    >
      <AlertTriangle size={17} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{title}</p>
        <p className="mt-0.5 break-words text-xs leading-relaxed">{message}</p>
      </div>
      {onRetry ? (
        <Button variant="secondary" onClick={onRetry} icon={<RefreshCw size={14} />} className="shrink-0">
          Retry
        </Button>
      ) : null}
    </div>
  )
}

export function InfoBanner({
  title,
  children,
  tone = 'info',
}: {
  title?: string
  children: ReactNode
  tone?: 'info' | 'warning' | 'success'
}) {
  const tones = {
    info: 'border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-900 dark:bg-sky-950/50 dark:text-sky-200',
    warning:
      'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200',
    success:
      'border-emerald-300 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200',
  }
  return (
    <div className={clsx('rounded-lg border px-4 py-3 text-xs leading-relaxed', tones[tone])}>
      {title ? <p className="font-semibold">{title}</p> : null}
      <div className={clsx(title && 'mt-1')}>{children}</div>
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Tabs                                                                      */
/* -------------------------------------------------------------------------- */

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: ReactNode; count?: number }[]
  active: string
  onChange: (id: string) => void
}) {
  return (
    <div
      className="inline-flex flex-wrap gap-1 rounded-lg border border-slate-200 bg-white p-1 dark:border-slate-800 dark:bg-slate-900"
      role="tablist"
    >
      {tabs.map((tab) => (
        <button
          key={tab.id}
          role="tab"
          type="button"
          aria-selected={active === tab.id}
          onClick={() => onChange(tab.id)}
          className={clsx(
            'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
            active === tab.id
              ? 'bg-brand-600 text-white'
              : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800',
          )}
        >
          {tab.label}
          {tab.count !== undefined ? (
            <span className="ml-1.5 rounded-full bg-black/10 px-1.5 text-[10px] dark:bg-white/10">{tab.count}</span>
          ) : null}
        </button>
      ))}
    </div>
  )
}

/* -------------------------------------------------------------------------- */
/* Collapsible section                                                       */
/* -------------------------------------------------------------------------- */

export function Disclosure({
  title,
  subtitle,
  children,
  defaultOpen = false,
  badge,
}: {
  title: ReactNode
  subtitle?: ReactNode
  children: ReactNode
  defaultOpen?: boolean
  badge?: ReactNode
}) {
  return (
    <details open={defaultOpen} className="group">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-1 py-2 text-sm font-semibold text-slate-800 marker:hidden dark:text-slate-100">
        <span className="flex items-center gap-2">
          {title}
          {badge}
        </span>
        <span className="text-xs font-normal text-slate-500 transition-transform group-open:rotate-90 dark:text-slate-400">
          ›
        </span>
      </summary>
      {subtitle ? <p className="mb-2 px-1 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p> : null}
      <div className="animate-fade-in">{children}</div>
    </details>
  )
}
