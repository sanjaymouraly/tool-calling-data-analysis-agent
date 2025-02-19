import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import Workspace from '../src/pages/Workspace'
import { ToastProvider } from '../src/hooks/useToast'
import type { AnalysisResult, Dataset, ProviderStatus } from '../src/lib/types'

vi.mock('../src/lib/api', async () => {
  const actual = await vi.importActual<typeof import('../src/lib/api')>('../src/lib/api')
  return {
    ...actual,
    api: {
      datasets: vi.fn(),
      providers: vi.fn(),
      ask: vi.fn(),
      history: vi.fn(),
    },
  }
})

import { api } from '../src/lib/api'

const datasets: Dataset[] = [
  {
    id: 'ds-1',
    name: 'Retail Orders',
    original_filename: 'retail_orders.csv',
    file_type: 'csv',
    sheet_name: null,
    row_count: 5018,
    column_count: 14,
    size_bytes: 1024,
    currency: 'USD',
    is_demo: true,
    is_approved: false,
    description: null,
    lineage_id: 'lin-1',
    version: 1,
    created_at: '2024-05-17T00:00:00Z',
    updated_at: '2024-05-17T00:00:00Z',
    file_hash: 'a'.repeat(64),
  },
]

const providers: ProviderStatus[] = [
  {
    provider: 'free',
    label: 'Free guided mode (no API key)',
    requires_key: false,
    base_url: '',
    model: 'deterministic',
    has_key: false,
    masked_key: null,
    key_hint: null,
    supports_native_tools: false,
    supports_model_listing: false,
    notes: 'Offline',
    source: 'environment',
  },
]

const result: AnalysisResult = {
  id: 'a-1',
  conversation_id: 'c-1',
  question: 'What were monthly sales and growth rates?',
  answer: '### Result\n**Total revenue: $1,234.56**\n\n### Evidence\n- **Retail Orders**',
  status: 'completed',
  plan: { steps: [] },
  tool_trace: [
    {
      step: 1,
      tool: 'time_series',
      status: 'success',
      input: { dataset_id: 'ds-1' },
      output: { data: { periods: [{ period: '2024-01', revenue: 100 }] } },
    },
  ],
  evidence: {
    datasets: [
      {
        id: 'ds-1',
        name: 'Retail Orders',
        version: 1,
        row_count: 5018,
        column_count: 14,
        file_hash: 'a'.repeat(64),
      },
    ],
    tool_evidence: [],
    verifiable: true,
    note: 'grounded',
  },
  how_calculated: {
    plan: { steps: [] },
    steps: [],
    datasets: [],
    provider: 'free',
    model: null,
    definitions: {},
    assumptions: [],
    exclusions: [],
    execution_metadata: {},
  },
  charts: [],
  usage: {},
  verification: { all_verified: true },
  provider: 'free',
  model: null,
  latency_ms: 42,
  states: ['inspect', 'plan', 'execute', 'answer'],
}

function renderWorkspace() {
  return render(
    <ToastProvider>
      <MemoryRouter initialEntries={['/workspace']}>
        <Routes>
          <Route path="/workspace" element={<Workspace />} />
        </Routes>
      </MemoryRouter>
    </ToastProvider>,
  )
}

beforeEach(() => {
  vi.mocked(api.datasets).mockResolvedValue(datasets)
  vi.mocked(api.providers).mockResolvedValue(providers)
  vi.mocked(api.history).mockResolvedValue([])
  vi.mocked(api.ask).mockResolvedValue(result)
})

describe('Workspace', () => {
  it('lists the datasets that can be authorised', async () => {
    renderWorkspace()
    expect(await screen.findByRole('button', { name: /Retail Orders/ })).toBeInTheDocument()
  })

  it('runs a question and renders the grounded answer', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    const input = await screen.findByLabelText('Question')
    await user.type(input, 'What were monthly sales and growth rates?')
    await user.click(screen.getByRole('button', { name: /^Ask$/ }))

    expect(await screen.findByText('Evidence-backed answer')).toBeInTheDocument()
    expect(screen.getByText('Total revenue: $1,234.56')).toBeInTheDocument()
    expect(api.ask).toHaveBeenCalledWith(
      expect.objectContaining({ question: 'What were monthly sales and growth rates?' }),
    )
  })

  it('shows the tool trace and the evidence panel', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    const input = await screen.findByLabelText('Question')
    await user.type(input, 'What were monthly sales and growth rates?')
    await user.click(screen.getByRole('button', { name: /^Ask$/ }))
    await screen.findByText('Evidence-backed answer')

    await user.click(screen.getByRole('button', { name: /Tool trace/ }))
    expect(await screen.findByText('time_series')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /How this was calculated/ }))
    expect(await screen.findByText('Source data')).toBeInTheDocument()
  })

  it('refuses to run without a dataset', async () => {
    const user = userEvent.setup()
    renderWorkspace()
    const input = await screen.findByLabelText('Question')
    await user.type(input, 'What were monthly sales?')
    // deselect the only dataset
    await user.click(screen.getByRole('button', { name: /Retail Orders/ }))
    await user.click(screen.getByRole('button', { name: /^Ask$/ }))
    expect(api.ask).not.toHaveBeenCalled()
  })
})
