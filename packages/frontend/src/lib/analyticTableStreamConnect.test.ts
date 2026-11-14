import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchFleetTableStream } from '../api/bff'
import { connectAnalyticTableStream } from './analyticTableStreamConnect'
import { requestBackfillWalkStop } from './backfillWalkStop'
import {
  flushMicrotasks,
  stubFetchHoldingBackfillWalkStops,
} from './backfillWalkStopTestFixtures'

const scope = { gameId: '100', turn: 12, perspective: 1 }

function connectFleetTableStream(signal: AbortSignal) {
  return connectAnalyticTableStream(scope, [8], {
    fetchStream: fetchFleetTableStream,
    signal,
    onEvent: () => {},
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('connectAnalyticTableStream', () => {
  it('waits for a pending stop for its game before connecting', async () => {
    const { releaseStops, requestUrls } = stubFetchHoldingBackfillWalkStops('')
    const stop = requestBackfillWalkStop(scope.gameId)

    const connect = connectFleetTableStream(new AbortController().signal)
    await flushMicrotasks()
    expect(requestUrls()).toEqual([])

    releaseStops()
    await stop

    await expect(connect).resolves.toBe('ok')
    expect(requestUrls()).toHaveLength(1)
  })

  it('does not wait for a stop pending for another game', async () => {
    const { releaseStops, requestUrls } = stubFetchHoldingBackfillWalkStops('')
    const otherGameStop = requestBackfillWalkStop('200')

    await expect(connectFleetTableStream(new AbortController().signal)).resolves.toBe('ok')
    expect(requestUrls()).toHaveLength(1)

    releaseStops()
    await otherGameStop
  })

  it('returns aborted once the stop settles when aborted while waiting', async () => {
    const { releaseStops } = stubFetchHoldingBackfillWalkStops('')
    const controller = new AbortController()
    const stop = requestBackfillWalkStop(scope.gameId)
    let isSettled = false

    const connect = connectFleetTableStream(controller.signal).finally(() => {
      isSettled = true
    })
    controller.abort()
    await flushMicrotasks()
    expect(isSettled).toBe(false)

    releaseStops()
    await stop

    await expect(connect).resolves.toBe('aborted')
  })
})
