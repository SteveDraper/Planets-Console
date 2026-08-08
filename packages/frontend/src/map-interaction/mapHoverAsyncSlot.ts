/**
 * Manager-owned async sample slot for **map hover** (cartography sampling).
 *
 * Debounce / cancel / stale-seq live here so contributors only supply
 * ``fetch(hit) → blocks``. Pure (no React) so Phase 2 surface can wrap it.
 */

export type AsyncSampleSlotRequest = {
  /** Monotonic hit epoch from the pane pointer. */
  hitEpoch: number
  /** Contributor request key (e.g. ``mapX:mapY``). */
  requestKey: string
}

export type AsyncSampleSlotResult<T> =
  | { status: 'idle' }
  | { status: 'pending'; request: AsyncSampleSlotRequest }
  | { status: 'ready'; request: AsyncSampleSlotRequest; value: T }
  | { status: 'error'; request: AsyncSampleSlotRequest; error: unknown }
  | { status: 'cancelled' }
  /** This ``schedule`` call lost to a newer schedule or cancel. */
  | { status: 'superseded' }

export type AsyncSampleSlotOptions = {
  /** Debounce before invoking ``fetch``. Default 100ms (cartography hover). */
  debounceMs?: number
  setTimeoutFn?: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>
  clearTimeoutFn?: (id: ReturnType<typeof setTimeout>) => void
}

const DEFAULT_DEBOUNCE_MS = 100

/**
 * Creates a single-flight async slot with debounce and stale discard.
 *
 * Only the latest ``schedule`` wins; older in-flight fetches are ignored when
 * they resolve (seq / key mismatch), and ``cancel`` clears pending work.
 * Each ``schedule`` promise settles for *that* call (ready/error/superseded/
 * cancelled) without overwriting a newer slot snapshot.
 */
export function createAsyncSampleSlot<T>(options: AsyncSampleSlotOptions = {}) {
  const debounceMs = options.debounceMs ?? DEFAULT_DEBOUNCE_MS
  const setTimeoutFn = options.setTimeoutFn ?? setTimeout
  const clearTimeoutFn = options.clearTimeoutFn ?? clearTimeout

  let seq = 0
  let debounceTimer: ReturnType<typeof setTimeout> | null = null
  let active: AsyncSampleSlotRequest | null = null
  let lastResult: AsyncSampleSlotResult<T> = { status: 'idle' }
  let settleCurrent: ((result: AsyncSampleSlotResult<T>) => void) | null = null

  function clearDebounce(): void {
    if (debounceTimer != null) {
      clearTimeoutFn(debounceTimer)
      debounceTimer = null
    }
  }

  function snapshot(): AsyncSampleSlotResult<T> {
    return lastResult
  }

  function settleWaiter(result: AsyncSampleSlotResult<T>): void {
    const settle = settleCurrent
    settleCurrent = null
    settle?.(result)
  }

  function cancel(): void {
    clearDebounce()
    seq += 1
    active = null
    lastResult = { status: 'cancelled' }
    settleWaiter({ status: 'cancelled' })
  }

  function reset(): void {
    clearDebounce()
    seq += 1
    active = null
    lastResult = { status: 'idle' }
    settleWaiter({ status: 'superseded' })
  }

  /**
   * Schedule a fetch for ``request``. Resolves for this call only; a superseded
   * or cancelled call does not mutate a newer slot snapshot to its own value.
   */
  function schedule(
    request: AsyncSampleSlotRequest,
    fetch: () => Promise<T>
  ): Promise<AsyncSampleSlotResult<T>> {
    clearDebounce()
    // A newer schedule supersedes any waiter still pending from the prior call.
    settleWaiter({ status: 'superseded' })
    seq += 1
    const scheduledSeq = seq
    active = request
    lastResult = { status: 'pending', request }

    return new Promise((resolve) => {
      settleCurrent = resolve

      debounceTimer = setTimeoutFn(() => {
        debounceTimer = null
        if (scheduledSeq !== seq) {
          resolve({ status: 'superseded' })
          if (settleCurrent === resolve) settleCurrent = null
          return
        }
        void fetch()
          .then((value) => {
            if (scheduledSeq !== seq) {
              resolve({ status: 'superseded' })
              if (settleCurrent === resolve) settleCurrent = null
              return
            }
            if (
              active == null ||
              active.hitEpoch !== request.hitEpoch ||
              active.requestKey !== request.requestKey
            ) {
              resolve({ status: 'superseded' })
              if (settleCurrent === resolve) settleCurrent = null
              return
            }
            const ready: AsyncSampleSlotResult<T> = {
              status: 'ready',
              request,
              value,
            }
            lastResult = ready
            settleCurrent = null
            resolve(ready)
          })
          .catch((error: unknown) => {
            if (scheduledSeq !== seq) {
              resolve({ status: 'superseded' })
              if (settleCurrent === resolve) settleCurrent = null
              return
            }
            if (
              active == null ||
              active.hitEpoch !== request.hitEpoch ||
              active.requestKey !== request.requestKey
            ) {
              resolve({ status: 'superseded' })
              if (settleCurrent === resolve) settleCurrent = null
              return
            }
            const errored: AsyncSampleSlotResult<T> = {
              status: 'error',
              request,
              error,
            }
            lastResult = errored
            settleCurrent = null
            resolve(errored)
          })
      }, debounceMs)
    })
  }

  return { schedule, cancel, reset, snapshot }
}

export type AsyncSampleSlot<T> = ReturnType<typeof createAsyncSampleSlot<T>>
