import { describe, expect, it, vi } from 'vitest'
import { postBackfillWalksStop } from '../api/backfillWalksClient'
import { connectAnalyticTableStream } from './analyticTableStreamConnect'
import { requestBackfillWalkStop } from './backfillWalkStop'
import { deferredStopResponse, flushMicrotasks } from './backfillWalkStopTestFixtures'

vi.mock('../api/backfillWalksClient', () => ({
  postBackfillWalksStop: vi.fn(),
}))

const postStop = vi.mocked(postBackfillWalksStop)

const scope = { gameId: '100', turn: 12, perspective: 1 }

function heldStop(): () => void {
  const response = deferredStopResponse()
  postStop.mockReturnValueOnce(response.promise)
  return response.resolve
}

describe('connectAnalyticTableStream', () => {
  it('waits for a pending stop for its game before connecting', async () => {
    const releaseStop = heldStop()
    const fetchStream = vi.fn(async () => {})
    void requestBackfillWalkStop(scope.gameId)

    const connect = connectAnalyticTableStream(scope, [8], {
      fetchStream,
      signal: new AbortController().signal,
      onEvent: () => {},
    })
    await flushMicrotasks()
    expect(fetchStream).not.toHaveBeenCalled()

    releaseStop()

    await expect(connect).resolves.toBe('ok')
    expect(fetchStream).toHaveBeenCalledTimes(1)
  })

  it('does not wait for a stop pending for another game', async () => {
    const releaseStop = heldStop()
    const fetchStream = vi.fn(async () => {})
    const otherGameStop = requestBackfillWalkStop('200')

    await expect(
      connectAnalyticTableStream(scope, [8], {
        fetchStream,
        signal: new AbortController().signal,
        onEvent: () => {},
      })
    ).resolves.toBe('ok')
    expect(fetchStream).toHaveBeenCalledTimes(1)

    releaseStop()
    await otherGameStop
  })

  it('does not connect when aborted while waiting for the stop', async () => {
    const releaseStop = heldStop()
    const fetchStream = vi.fn(async () => {})
    const controller = new AbortController()
    void requestBackfillWalkStop(scope.gameId)

    const connect = connectAnalyticTableStream(scope, [8], {
      fetchStream,
      signal: controller.signal,
      onEvent: () => {},
    })
    controller.abort()
    releaseStop()

    await expect(connect).resolves.toBe('aborted')
    expect(fetchStream).not.toHaveBeenCalled()
  })
})
