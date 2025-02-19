import { describe, expect, it } from 'vitest'
import { formatBytes, formatCurrency, formatNumber, formatPercent, relativeTime, shortHash, truncate } from '../src/lib/format'

describe('formatNumber', () => {
  it('formats integers without decimals', () => {
    expect(formatNumber(1234, 0)).toBe('1,234')
  })

  it('formats decimals with a maximum precision', () => {
    expect(formatNumber(1234.5678, 2)).toBe('1,234.57')
  })

  it('renders a dash for missing values', () => {
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(undefined)).toBe('—')
    expect(formatNumber('not a number')).toBe('not a number')
  })
})

describe('formatCurrency', () => {
  it('formats a currency', () => {
    expect(formatCurrency(1234.5, 'USD')).toContain('1,234.50')
  })

  it('handles null', () => {
    expect(formatCurrency(null)).toBe('—')
  })
})

describe('formatPercent', () => {
  it('formats a percentage', () => {
    expect(formatPercent(45.678)).toBe('45.68%')
  })

  it('reports an undefined percentage', () => {
    expect(formatPercent(null)).toBe('undefined')
  })
})

describe('formatBytes', () => {
  it('formats byte sizes', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(1024)).toBe('1.0 KB')
    expect(formatBytes(1024 * 1024 * 3)).toBe('3.0 MB')
  })
})

describe('truncate', () => {
  it('truncates long strings', () => {
    expect(truncate('abcdefghij', 5)).toBe('abcd…')
  })

  it('keeps short strings', () => {
    expect(truncate('abc', 5)).toBe('abc')
  })
})

describe('shortHash', () => {
  it('shortens a hash', () => {
    expect(shortHash('0123456789abcdef')).toBe('0123456789ab')
  })

  it('handles a missing hash', () => {
    expect(shortHash(null)).toBe('—')
  })
})

describe('relativeTime', () => {
  it('describes a recent timestamp', () => {
    const now = new Date().toISOString()
    expect(relativeTime(now)).toBe('just now')
  })

  it('handles an invalid timestamp', () => {
    expect(relativeTime('not-a-date')).toBe('—')
  })
})
