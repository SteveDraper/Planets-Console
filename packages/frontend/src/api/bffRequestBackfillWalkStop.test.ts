import { afterEach, describe, expect, it, vi } from 'vitest'
import { pendingBackfillWalkStop, requestBackfillWalkStop } from '../lib/backfillWalkStop'
import {
  flushMicrotasks,
  stubFetchHoldingBackfillWalkStops,
} from '../lib/backfillWalkStopTestFixtures'
import { fetchAnalyticTable, fetchGames, fetchStoredGameInfo } from './bff'
import { postBackfillWalksStop } from './backfillWalksClient'
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
