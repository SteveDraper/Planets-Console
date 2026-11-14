import { afterEach, describe, expect, it, vi } from 'vitest'
import { BffHttpError } from './bffHttpError'
import { postBackfillWalksStop } from './backfillWalksClient'

describe('postBackfillWalksStop', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts the stop for the game with a timeout signal and accepts 204', async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(null, { status: 204 })))
    vi.stubGlobal('fetch', fetchMock)

    await expect(postBackfillWalksStop('628580')).resolves.toBeUndefined()

    expect(fetchMock).toHaveBeenCalledWith('/bff/games/628580/backfill-walks/stop', {
      method: 'POST',
      signal: expect.any(AbortSignal),
    })
  })

  it('throws a BFF HTTP error naming the route on failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(null, { status: 503, statusText: '503' })))
    )

    await expect(postBackfillWalksStop('628580')).rejects.toSatisfy((thrown: unknown) => {
      expect(thrown).toBeInstanceOf(BffHttpError)
      expect((thrown as BffHttpError).status).toBe(503)
      expect((thrown as Error).message).toMatch(/POST \/bff\/games\/628580\/backfill-walks\/stop/)
      return true
    })
  })
})
