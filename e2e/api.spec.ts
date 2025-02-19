import { expect, test } from '@playwright/test'

test.describe('REST API', () => {
  test('the health endpoint responds', async ({ request }) => {
    const response = await request.get('/api/health')
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body.status).toBe('ok')
  })

  test('the tool catalogue is finite and documented', async ({ request }) => {
    const response = await request.get('/api/analysis/tools')
    expect(response.status()).toBe(200)
    const tools = await response.json()
    expect(tools.length).toBeGreaterThan(10)
    for (const tool of tools) {
      expect(tool.name).toBeTruthy()
      expect(tool.input_schema.type).toBe('object')
    }
  })

  test('an unknown API path returns a JSON 404', async ({ request }) => {
    const response = await request.get('/api/not-a-real-endpoint')
    expect(response.status()).toBe(404)
    const body = await response.json()
    expect(body.error).toBeTruthy()
  })

  test('the provider list never contains a raw API key', async ({ request }) => {
    const response = await request.get('/api/settings/providers')
    expect(response.status()).toBe(200)
    const providers = await response.json()
    for (const provider of providers) {
      expect(provider).not.toHaveProperty('api_key')
    }
  })

  test('an unknown provider is rejected', async ({ request }) => {
    const datasets = await (await request.get('/api/datasets')).json()
    const response = await request.post('/api/analysis/query', {
      data: {
        question: 'What is the revenue?',
        dataset_ids: [datasets[0].id],
        provider: 'not-a-provider',
      },
    })
    expect(response.status()).toBe(422)
  })

  test('a question with an unauthorised dataset is refused', async ({ request }) => {
    const response = await request.post('/api/analysis/query', {
      data: {
        question: 'What is the revenue?',
        dataset_ids: ['00000000-0000-0000-0000-000000000000'],
      },
    })
    expect(response.status()).toBe(422)
  })
})
