import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { postBackfillWalksStop } from '../api/backfillWalksClient'
import {
  pendingBackfillWalkStop,
  requestBackfillWalkStop,
  resetPendingBackfillWalkStops,
} from './backfillWalkStop'
import { deferredStopResponse } from './backfillWalkStopTestFixtures'

vi.mock('../api/backfillWalksClient', () => ({
  postBackfillWalksStop: vi.fn(),
}))

const postStop = vi.mocked(postBackfillWalksStop)

beforeEach(() => {
  postStop.mockReset()
  postStop.mockResolvedValue(undefined)
})

afterEach(() => {
  resetPendingBackfillWalkStops()
})

describe('requestBackfillWalkStop', () => {
  it('chains a second stop for the same game after the first settles', async () => {
    const first = deferredStopResponse()
    postStop.mockReturnValueOnce(first.promise)

    const firstStop = requestBackfillWalkStop('100')
    const secondStop = requestBackfillWalkStop('100')
    await Promise.resolve()

    expect(postStop).toHaveBeenCalledTimes(1)
    expect(pendingBackfillWalkStop('100')).toBe(secondStop)

    first.resolve()
    await firstStop
    await secondStop

    expect(postStop).toHaveBeenCalledTimes(2)
    expect(postStop).toHaveBeenNthCalledWith(2, '100')
  })

  it('does not chain stops for different games', async () => {
    const first = deferredStopResponse()
    postStop.mockReturnValueOnce(first.promise)

    const stopA = requestBackfillWalkStop('100')
    const stopB = requestBackfillWalkStop('200')
    await stopB

    expect(postStop).toHaveBeenCalledTimes(2)
    expect(pendingBackfillWalkStop('100')).toBe(stopA)
    first.resolve()
    await stopA
  })

  it('deletes the entry once its chain settles', async () => {
    const stop = requestBackfillWalkStop('100')
    expect(pendingBackfillWalkStop('100')).toBe(stop)

    await stop

    expect(pendingBackfillWalkStop('100')).toBeUndefined()
  })

  it('keeps a later chain when an earlier one settles', async () => {
    const first = deferredStopResponse()
    const second = deferredStopResponse()
    postStop.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const firstStop = requestBackfillWalkStop('100')
    const secondStop = requestBackfillWalkStop('100')
    first.resolve()
    await firstStop

    expect(pendingBackfillWalkStop('100')).toBe(secondStop)
    second.resolve()
    await secondStop
    expect(pendingBackfillWalkStop('100')).toBeUndefined()
  })

  it('resolves and logs when the stop fails, and a chained stop still runs', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    postStop.mockRejectedValueOnce(new Error('503 (POST /bff/games/100/backfill-walks/stop)'))

    const failedStop = requestBackfillWalkStop('100')
    const chainedStop = requestBackfillWalkStop('100')

    await expect(failedStop).resolves.toBeUndefined()
    await expect(chainedStop).resolves.toBeUndefined()
    expect(postStop).toHaveBeenCalledTimes(2)
    expect(warn).toHaveBeenCalledTimes(1)
    expect(pendingBackfillWalkStop('100')).toBeUndefined()
    warn.mockRestore()
  })
})
