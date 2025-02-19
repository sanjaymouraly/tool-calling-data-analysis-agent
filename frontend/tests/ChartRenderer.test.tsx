import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ChartRenderer } from '../src/components/ChartRenderer'
import type { ChartSpec } from '../src/lib/types'

const spec: ChartSpec = {
  chart_type: 'bar',
  title: 'Revenue by product',
  x_key: 'x',
  y_keys: ['Revenue'],
  data: [
    { x: 'Chair', Revenue: 400 },
    { x: 'Desk', Revenue: 250 },
  ],
  x_label: 'Product',
  y_label: 'Revenue',
}

describe('ChartRenderer', () => {
  it('renders a chart with a title', () => {
    render(<ChartRenderer spec={spec} />)
    expect(screen.getByText('Revenue by product')).toBeInTheDocument()
  })

  it('renders an empty state without data', () => {
    render(<ChartRenderer spec={{ ...spec, data: [] }} />)
    expect(screen.getByText('No chart data')).toBeInTheDocument()
  })
})
