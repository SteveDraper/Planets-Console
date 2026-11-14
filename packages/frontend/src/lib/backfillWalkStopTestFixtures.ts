import { vi } from 'vitest'

/** A stop response the test resolves by hand. */
export function deferredStopResponse() {
  let resolve!: () => void
  const promise = new Promise<void>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

/** Let queued promise reactions (a chained stop's POST, a connect's await) run. */
export async function flushMicrotasks(): Promise<void> {
  for (let tick = 0; tick < 5; tick += 1) {
    await Promise.resolve()
  }
}

/**
 * Stub `fetch` so every Backfill walk stop POST is held until `releaseStops()`, and every other
 * request answers 200 at once with `responseBody`. Like `fetch`, it rejects a request whose signal
 * is already aborted. `requestUrls()` lists the requests other than stops, in send order.
 */
export function stubFetchHoldingBackfillWalkStops(responseBody = '{}') {
  const heldStops: (() => void)[] = []
  const fetchMock = vi.fn((url: string, init?: RequestInit): Promise<Response> => {
    if (init?.signal?.aborted) {
      return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'))
    }
    if (url.endsWith('/backfill-walks/stop')) {
      return new Promise((resolve) => {
        heldStops.push(() => resolve(new Response(null, { status: 204 })))
      })
    }
    return Promise.resolve(new Response(responseBody, { status: 200 }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return {
    releaseStops: () => {
      heldStops.splice(0).forEach((release) => release())
    },
    requestUrls: () =>
      fetchMock.mock.calls
        .map(([url]) => url)
        .filter((url) => !url.endsWith('/backfill-walks/stop')),
  }
}
