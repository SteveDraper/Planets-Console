import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createAsyncSampleSlot } from './mapHoverAsyncSlot'

describe('createAsyncSampleSlot', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('debounces then resolves ready for the latest request', async () => {
    const slot = createAsyncSampleSlot<string>({ debounceMs: 100 })
    const fetch = vi.fn().mockResolvedValue('sample-a')

    const pending = slot.schedule(
      { hitEpoch: 1, requestKey: '10:20' },
      fetch
    )
    expect(slot.snapshot().status).toBe('pending')
    expect(fetch).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(100)
    const result = await pending

    expect(fetch).toHaveBeenCalledTimes(1)
    expect(result).toEqual({
      status: 'ready',
      request: { hitEpoch: 1, requestKey: '10:20' },
      value: 'sample-a',
    })
  })

  it('cancel prevents a pending debounce from fetching', async () => {
    const slot = createAsyncSampleSlot<string>({ debounceMs: 100 })
    const fetch = vi.fn().mockResolvedValue('should-not-run')

    const pending = slot.schedule(
      { hitEpoch: 1, requestKey: '1:1' },
      fetch
    )
    slot.cancel()
    const result = await pending
    await vi.advanceTimersByTimeAsync(100)

    expect(fetch).not.toHaveBeenCalled()
    expect(result.status).toBe('cancelled')
    expect(slot.snapshot().status).toBe('cancelled')
  })

  it('discards stale in-flight results when a newer schedule wins', async () => {
    const slot = createAsyncSampleSlot<string>({ debounceMs: 0 })
    let resolveStale!: (value: string) => void
    const staleFetch = vi.fn(
      () =>
        new Promise<string>((resolve) => {
          resolveStale = resolve
        })
    )
    const freshFetch = vi.fn().mockResolvedValue('fresh')

    const stalePending = slot.schedule(
      { hitEpoch: 1, requestKey: 'stale' },
      staleFetch
    )
    await vi.advanceTimersByTimeAsync(0)

    const freshPending = slot.schedule(
      { hitEpoch: 2, requestKey: 'fresh' },
      freshFetch
    )
    await vi.advanceTimersByTimeAsync(0)

    resolveStale('stale-value')
    await expect(stalePending).resolves.toEqual({ status: 'superseded' })

    await expect(freshPending).resolves.toEqual({
      status: 'ready',
      request: { hitEpoch: 2, requestKey: 'fresh' },
      value: 'fresh',
    })
    expect(slot.snapshot()).toEqual({
      status: 'ready',
      request: { hitEpoch: 2, requestKey: 'fresh' },
      value: 'fresh',
    })
  })
})
