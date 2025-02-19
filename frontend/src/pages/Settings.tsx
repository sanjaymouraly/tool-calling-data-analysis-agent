import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, KeyRound, Loader2, Plug, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import type { AppConfig, ProviderStatus } from '../lib/types'
import { formatNumber } from '../lib/format'
import { Badge, Button, Card, ErrorBanner, Field, InfoBanner, Input, Select } from '../components/ui'
import { useToast } from '../hooks/useToast'

interface Form {
  provider: string
  base_url: string
  api_key: string
  model: string
}

export default function Settings() {
  const [providers, setProviders] = useState<ProviderStatus[]>([])
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [form, setForm] = useState<Form>({ provider: 'openai', base_url: '', api_key: '', model: '' })
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [models, setModels] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [usage, setUsage] = useState<Record<string, unknown> | null>(null)
  const toast = useToast()

  const load = useCallback(() => {
    api.providers().then(setProviders).catch((err: Error) => setError(err.message))
    api.config().then(setConfig).catch(() => undefined)
    api.usage().then(setUsage).catch(() => undefined)
  }, [])

  useEffect(load, [load])

  const selectProvider = (name: string) => {
    const status = providers.find((item) => item.provider === name)
    setForm({
      provider: name,
      base_url: status?.base_url ?? '',
      api_key: '',
      model: status?.model ?? '',
    })
    setResult(null)
    setModels([])
  }

  const test = async () => {
    setTesting(true)
    setResult(null)
    setError(null)
    try {
      const response = await api.testProvider({
        provider: form.provider,
        base_url: form.base_url || undefined,
        api_key: form.api_key || undefined,
        model: form.model || undefined,
      })
      setResult(response)
      if (response.ok) toast.success('Connection successful', `${form.provider} responded.`)
      else toast.error('Connection failed', String(response.error ?? 'unknown error'))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setTesting(false)
    }
  }

  const discoverModels = async () => {
    try {
      const response = await api.providerModels(form.provider)
      setModels(response.models)
      if (response.models.length) {
        toast.success('Models discovered', `${response.models.length} model(s) available.`)
      } else {
        toast.info('No models listed', 'The provider did not return a model list - enter the name manually.')
      }
    } catch (err) {
      toast.error('Could not list models', (err as Error).message)
    }
  }

  const save = async () => {
    setSaving(true)
    try {
      await api.saveProvider({
        provider: form.provider,
        base_url: form.base_url || undefined,
        api_key: form.api_key || undefined,
        model: form.model || undefined,
      })
      toast.success('Provider saved', 'The key is stored encrypted and is never returned by the API.')
      setForm((current) => ({ ...current, api_key: '' }))
      load()
    } catch (err) {
      toast.error('Save failed', (err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const remove = async (provider: string) => {
    try {
      await fetch(`/api/settings/providers/${provider}`, { method: 'DELETE' })
      toast.success('Provider configuration removed', provider)
      load()
    } catch {
      toast.error('Could not remove the configuration')
    }
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600 dark:text-slate-400">
          Configure an AI provider, or keep using the free deterministic mode. Keys are stored encrypted at
          rest, are never written to logs and are never returned by the API.
        </p>
      </header>

      {error ? <ErrorBanner message={error} /> : null}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="space-y-5">
          <Card
            title="Provider wizard"
            description="Direct API keys for hosted providers, or a local endpoint. The free mode needs no key."
          >
            <div className="grid gap-4 md:grid-cols-2">
              <Field label="Provider" htmlFor="provider">
                <Select id="provider" value={form.provider} onChange={(event) => selectProvider(event.target.value)}>
                  {providers.map((provider) => (
                    <option key={provider.provider} value={provider.provider}>
                      {provider.label}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field
                label="Model"
                htmlFor="model"
                hint="Leave empty to use the documented default, or discover what the provider offers."
              >
                <Input
                  id="model"
                  value={form.model}
                  onChange={(event) => setForm({ ...form, model: event.target.value })}
                  placeholder={providers.find((p) => p.provider === form.provider)?.model ?? 'model name'}
                />
              </Field>

              <Field
                label="Base URL"
                htmlFor="base-url"
                hint="For a custom provider paste the OpenAI-compatible base URL, e.g. http://localhost:1234/v1"
              >
                <Input
                  id="base-url"
                  value={form.base_url}
                  onChange={(event) => setForm({ ...form, base_url: event.target.value })}
                  placeholder="https://api.openai.com/v1"
                />
              </Field>

              <Field
                label="API key"
                htmlFor="api-key"
                hint="Stored encrypted. Leave empty to keep the existing key."
              >
                <Input
                  id="api-key"
                  type="password"
                  autoComplete="off"
                  value={form.api_key}
                  onChange={(event) => setForm({ ...form, api_key: event.target.value })}
                  placeholder={form.provider === 'ollama' ? 'not required' : 'sk-...'}
                />
              </Field>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="secondary" onClick={() => void test()} loading={testing} icon={<Plug size={14} />}>
                Test connection
              </Button>
              <Button variant="secondary" onClick={() => void discoverModels()} icon={<RefreshCw size={14} />}>
                Discover models
              </Button>
              <Button variant="primary" onClick={() => void save()} loading={saving} icon={<KeyRound size={14} />}>
                Save configuration
              </Button>
            </div>

            {models.length ? (
              <div className="mt-4">
                <p className="mb-1.5 text-xs font-medium text-slate-700 dark:text-slate-300">
                  Available models ({models.length})
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {models.slice(0, 24).map((model) => (
                    <button
                      key={model}
                      type="button"
                      onClick={() => setForm({ ...form, model })}
                      className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 transition hover:border-brand-400 hover:bg-brand-50 dark:border-slate-800 dark:text-slate-300"
                    >
                      {model}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {result ? (
              <pre className="mt-4 max-h-56 overflow-auto rounded-lg bg-slate-900 p-3 font-mono text-[11px] text-slate-100">
                {JSON.stringify(result, null, 2)}
              </pre>
            ) : null}
          </Card>

          <Card
            title="Configured providers"
            description="What the application will use for each provider."
          >
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {providers.map((provider) => (
                <li key={provider.provider} className="flex items-start gap-3 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium capitalize">{provider.label}</span>
                      {provider.has_key ? (
                        <Badge tone="emerald">
                          <CheckCircle2 size={11} /> key set
                        </Badge>
                      ) : provider.requires_key ? (
                        <Badge tone="amber">key required</Badge>
                      ) : (
                        <Badge tone="slate">no key needed</Badge>
                      )}
                      <Badge tone="slate">{provider.source}</Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                      {provider.base_url || 'built-in'} - model {provider.model || 'default'}
                      {provider.masked_key ? ` - key ${provider.masked_key}` : ''}
                    </p>
                    <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{provider.notes}</p>
                  </div>
                  {provider.source === 'database' ? (
                    <button
                      type="button"
                      onClick={() => void remove(provider.provider)}
                      className="rounded p-1.5 text-slate-400 transition hover:bg-rose-50 hover:text-rose-600 dark:hover:bg-rose-950"
                      aria-label={`Remove ${provider.provider} configuration`}
                    >
                      <Trash2 size={14} />
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          </Card>

          <Card title="Cost controls" description="Budgets, limits and usage accounting.">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {[
                ['Max tool rounds', config?.max_tool_rounds],
                ['Tool timeout', config ? `${config.tool_timeout_seconds}s` : undefined],
                ['Token budget', config ? formatNumber(config.request_token_budget, 0) : undefined],
                ['Cost budget', config ? `$${config.request_cost_budget_usd.toFixed(2)}` : undefined],
              ].map(([label, value]) => (
                <div key={String(label)} className="rounded-lg bg-slate-50 p-3 dark:bg-slate-800/60">
                  <p className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</p>
                  <p className="mt-0.5 text-lg font-semibold tabular-nums">{value ?? '-'}</p>
                </div>
              ))}
            </div>
            <div className="mt-4">
              <p className="mb-1.5 text-xs font-medium text-slate-700 dark:text-slate-300">Recorded usage</p>
              {usage && usage.records && Array.isArray(usage.records) && usage.records.length ? (
                <div className="overflow-auto">
                  <table className="w-full text-xs">
                    <thead className="bg-slate-50 dark:bg-slate-800/60">
                      <tr>
                        {['Provider', 'Model', 'Tokens', 'Est. cost', 'Latency'].map((header) => (
                          <th key={header} className="px-3 py-1.5 text-left font-semibold">
                            {header}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(usage.records as Record<string, unknown>[]).slice(0, 8).map((record) => (
                        <tr key={String(record.id)} className="border-t border-slate-100 dark:border-slate-800">
                          <td className="px-3 py-1.5">{String(record.provider)}</td>
                          <td className="px-3 py-1.5 font-mono text-[11px]">{String(record.model ?? '-')}</td>
                          <td className="px-3 py-1.5 tabular-nums">{formatNumber(record.total_tokens, 0)}</td>
                          <td className="px-3 py-1.5 tabular-nums">${Number(record.estimated_cost_usd).toFixed(6)}</td>
                          <td className="px-3 py-1.5 tabular-nums">{formatNumber(record.latency_ms, 0)} ms</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-slate-500">
                  No provider calls recorded yet - the free deterministic mode does not use tokens.
                </p>
              )}
              <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
                Costs are estimates computed from configurable per-model prices, not a verified price list.
              </p>
            </div>
          </Card>
        </div>

        <aside className="space-y-4">
          <Card title="Security model">
            <ul className="space-y-2 text-xs text-slate-600 dark:text-slate-400">
              {[
                ['Tool allowlist', 'The model can only pick from a fixed set of typed tools.'],
                ['No code execution', 'No Python, SQL, shell or filesystem access - the server builds every query from templates.'],
                ['Dataset scoping', 'A request can only read the datasets you selected.'],
                ['Join approval', 'Cross-dataset joins need an explicit approved key.'],
                ['Injection defence', 'Cell values, file names and column names are data, never instructions.'],
                ['Export safety', 'CSV and XLSX exports neutralise spreadsheet formulas.'],
                ['Secret handling', 'Keys are encrypted at rest and only ever shown masked.'],
              ].map(([title, description]) => (
                <li key={title} className="flex gap-2">
                  <ShieldCheck size={14} className="mt-0.5 shrink-0 text-emerald-600" />
                  <span>
                    <span className="font-medium text-slate-800 dark:text-slate-100">{title}</span>{' '}
                    {description}
                  </span>
                </li>
              ))}
            </ul>
          </Card>

          <InfoBanner title="About the OpenAI option" tone="info">
            The OpenAI integration uses the <strong>platform API</strong>. A ChatGPT Plus or Pro subscription
            does not include API access and cannot be used here. The same applies to Anthropic: a console API key
            is required, not a claude.ai subscription.
          </InfoBanner>

          {config ? (
            <Card title="Runtime limits">
              <dl className="space-y-1.5 text-xs">
                {[
                  ['Upload size', `${config.max_upload_size_mb} MB`],
                  ['Tool rounds', String(config.max_tool_rounds)],
                  ['Result rows', formatNumber(config.max_tool_result_rows, 0)],
                  ['Tool timeout', `${config.tool_timeout_seconds}s`],
                  ['Version', config.version],
                  ['Environment', config.environment],
                ].map(([label, value]) => (
                  <div key={label} className="flex justify-between gap-2">
                    <dt className="text-slate-500 dark:text-slate-400">{label}</dt>
                    <dd className="font-medium">{value}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          ) : null}

          {testing ? (
            <p className="flex items-center gap-2 text-xs text-slate-500">
              <Loader2 size={13} className="animate-spin" /> Testing the connection…
            </p>
          ) : null}
        </aside>
      </div>
    </div>
  )
}
