import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { ApiError, api } from '../src/lib/api'

const originalFetch = globalThis.fetch

let mockFetch: ReturnType<typeof vi.fn>

beforeEach(() => {
  mockFetch = vi.fn()
  globalThis.fetch = mockFetch as unknown as typeof globalThis.fetch
})

afterEach(() => {
  globalThis.fetch = originalFetch
})

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('api client', () => {
  it('parses a successful response', async () => {
    mockFetch.mockResolvedValue(jsonResponse({ status: 'ok' }))
    await expect(api.health()).resolves.toEqual({ status: 'ok' })
  })

  it('raises a readable error for an API error payload', async () => {
    mockFetch.mockResolvedValue(
      jsonResponse({ error: { code: 'not_found', message: 'dataset missing' } }, 404),
    )
    const promise = api.dataset('abc')
    await expect(promise).rejects.toBeInstanceOf(ApiError)
    await expect(promise).rejects.toThrow('dataset missing')
  })

  it('falls back to the `detail` field', async () => {
    mockFetch.mockResolvedValue(jsonResponse({ detail: 'something specific' }, 400))
    await expect(api.datasets()).rejects.toThrow('something specific')
  })

  it('reports a network failure clearly', async () => {
    mockFetch.mockRejectedValue(new TypeError('Failed to fetch'))
    await expect(api.health()).rejects.toThrow(/Could not reach the backend/)
  })
})
