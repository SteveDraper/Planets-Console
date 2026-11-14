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
