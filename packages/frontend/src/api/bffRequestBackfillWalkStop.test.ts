import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  pendingBackfillWalkStop,
  requestBackfillWalkStop,
  resetPendingBackfillWalkStops,
} from '../lib/backfillWalkStop'
import {
  flushMicrotasks,
  stubFetchHoldingBackfillWalkStops,
} from '../lib/backfillWalkStopTestFixtures'
import { fetchAnalyticTable, fetchGames, fetchStoredGameInfo } from './bff'
import { BACKFILL_WALKS_STOP_TIMEOUT_MS, postBackfillWalksStop } from './backfillWalksClient'
import { putComputeDiagnosticsFreeze } from './bffComputeDiagnostics'

const SNAPSHOT_BODY = JSON.stringify({ shell: { gameId: 100, perspective: 1, turn: 12 } })

function scopeFor(gameId: string) {
  return { gameId, turn: 12, perspective: 1 }
}

/** One request per way a BFF request names its game. */
const GAME_SCOPED_REQUESTS = [
  {
    namesGameIn: 'path',
    send: (gameId: string) => fetchStoredGameInfo(gameId),
  },
  {
    namesGameIn: 'query',
    send: (gameId: string) => fetchAnalyticTable('fleet', scopeFor(gameId), () => {}),
  },
  {
    namesGameIn: 'body',
    send: (gameId: string) => putComputeDiagnosticsFreeze(scopeFor(gameId), true),
  },
]

afterEach(() => {
  resetPendingBackfillWalkStops()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('bffRequest and a pending Backfill walk stop', () => {
  it.each(GAME_SCOPED_REQUESTS)(
    'a request naming its game in the $namesGameIn waits for that game\'s pending stop',
    async ({ send }) => {
      const { releaseStops, requestUrls } = stubFetchHoldingBackfillWalkStops(SNAPSHOT_BODY)
      const stop = requestBackfillWalkStop('100')

      const request = send('100')
      await flushMicrotasks()
      expect(requestUrls()).toEqual([])

      releaseStops()
      await stop
      await request
      expect(requestUrls()).toHaveLength(1)
    }
  )

  it.each(GAME_SCOPED_REQUESTS)(
    'a request naming its game in the $namesGameIn does not wait for another game\'s stop',
    async ({ send }) => {
      const { releaseStops, requestUrls } = stubFetchHoldingBackfillWalkStops(SNAPSHOT_BODY)
      const otherGameStop = requestBackfillWalkStop('200')

      await send('100')
      expect(requestUrls()).toHaveLength(1)

      releaseStops()
      await otherGameStop
    }
  )

  it('a hung stop releases its game\'s waiting request when the stop times out', async () => {
    vi.useFakeTimers()
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { requestUrls } = stubFetchHoldingBackfillWalkStops(SNAPSHOT_BODY)
    const stop = requestBackfillWalkStop('100')

    const request = fetchStoredGameInfo('100')
    await vi.advanceTimersByTimeAsync(BACKFILL_WALKS_STOP_TIMEOUT_MS - 1)
    expect(requestUrls()).toEqual([])

    await vi.advanceTimersByTimeAsync(1)
    await expect(stop).resolves.toBeUndefined()
    await request
    expect(requestUrls()).toHaveLength(1)
    expect(warn).toHaveBeenCalledTimes(1)
    const [, timeoutError] = warn.mock.calls[0]
    expect(timeoutError).toBeInstanceOf(Error)
    expect((timeoutError as Error).message).toMatch(
      `Backfill walk stop for game 100 timed out after ${BACKFILL_WALKS_STOP_TIMEOUT_MS} ms`
    )
    expect((timeoutError as Error).message).not.toMatch('No HTTP response')
    expect((timeoutError as Error).cause).toMatchObject({ name: 'TimeoutError' })
    expect(pendingBackfillWalkStop('100')).toBeUndefined()
  })

  it('a stop that fails without timing out keeps the no-HTTP-response message', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new TypeError('Failed to fetch')))
    )

    await expect(requestBackfillWalkStop('100')).resolves.toBeUndefined()

    expect(warn).toHaveBeenCalledTimes(1)
    const [label, failure] = warn.mock.calls[0]
    expect(label).toBe('Backfill walk stop failed for game 100')
    expect((failure as Error).message).toMatch(
      'TypeError: Failed to fetch — POST /bff/games/100/backfill-walks/stop'
    )
    expect((failure as Error).message).toMatch('No HTTP response')
    expect((failure as Error).message).not.toMatch('timed out')
  })

  it('a request naming no game does not wait for any pending stop', async () => {
    const { releaseStops, requestUrls } = stubFetchHoldingBackfillWalkStops('{"games":[]}')
    const stop = requestBackfillWalkStop('100')

    await fetchGames()
    expect(requestUrls()).toEqual(['/bff/games'])

    releaseStops()
    await stop
  })

  it('the stop itself does not wait for its game\'s pending stop', async () => {
    const { releaseStops } = stubFetchHoldingBackfillWalkStops()
    const pendingStop = requestBackfillWalkStop('100')
    await flushMicrotasks()

    const directStop = postBackfillWalksStop('100')
    await flushMicrotasks()
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(2)

    releaseStops()
    await Promise.all([pendingStop, directStop])
    expect(pendingBackfillWalkStop('100')).toBeUndefined()
  })
})
