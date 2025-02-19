export function formatNumber(value: unknown, digits = 2): string {
  if (value === null || value === undefined || value === '') return '—'
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) return String(value)
  return numeric.toLocaleString(undefined, {
    minimumFractionDigits: Number.isInteger(numeric) ? 0 : digits,
    maximumFractionDigits: digits,
  })
}

export function formatCurrency(value: unknown, currency = 'USD'): string {
  if (value === null || value === undefined) return '—'
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) return String(value)
  try {
    return numeric.toLocaleString(undefined, {
      style: 'currency',
      currency,
      maximumFractionDigits: 2,
    })
  } catch {
    return `${numeric.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${currency}`
  }
}

export function formatPercent(value: unknown, digits = 2): string {
  if (value === null || value === undefined) return 'undefined'
  const numeric = typeof value === 'number' ? value : Number(value)
  if (Number.isNaN(numeric)) return 'undefined'
  return `${numeric.toLocaleString(undefined, { maximumFractionDigits: digits })}%`
}

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)))
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

export function formatDate(value: string | Date | undefined): string {
  if (!value) return '—'
  const date = typeof value === 'string' ? new Date(value) : value
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function relativeTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  return date.toLocaleDateString()
}

export function shortHash(hash?: string | null): string {
  if (!hash) return '—'
  return hash.slice(0, 12)
}

export function truncate(value: string, length = 120): string {
  if (!value) return ''
  return value.length > length ? `${value.slice(0, length - 1)}…` : value
}
