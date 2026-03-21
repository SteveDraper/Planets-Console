/**
 * TanStack Query retry policy for BFF fetch-backed queries.
 *
 * planets.nu sometimes returns 502 for non-transient failures (e.g. forbidden perspective);
 * retrying those only adds delay. We retry only statuses and errors that are commonly transient.
 */

const MAX_FAILURE_COUNT_BEFORE_STOP = 3

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** HTTP status inferred from our Error messages (see api/bff.ts). */
export function parseHttpStatusFromErrorMessage(message: string): number | null {
  const t = message.trim()
  const leading = /^(\d{3})(?=\D|$)/.exec(t)
  if (leading) {
    const n = Number(leading[1])
    return Number.isFinite(n) ? n : null
  }
  const lower = t.toLowerCase()
  if (/\bbad gateway\b/.test(lower)) {
    return 502
  }
  if (/\bgateway timeout\b/.test(lower)) {
    return 504
  }
  if (/\bservice unavailable\b/.test(lower)) {
    return 503
  }
  if (/\brequest timeout\b/.test(lower)) {
    return 408
  }
  if (/\binternal server error\b/.test(lower)) {
    return 500
  }
  return null
}

function isLikelyNetworkFailure(error: unknown): boolean {
  if (error instanceof TypeError) {
    return true
  }
  const lower = errorMessage(error).toLowerCase()
  if (lower.includes('failed to fetch')) {
    return true
  }
  if (lower.includes('networkerror')) {
    return true
  }
  if (lower.includes('load failed')) {
    return true
  }
  if (lower.includes('network request failed')) {
    return true
  }
  return false
}

function isTransientHttpStatus(code: number): boolean {
  return code === 408 || code === 503 || code === 504
}

/**
 * Used as TanStack Query `retry` callback. Retries only network-style failures and
 * 408 / 503 / 504. Does not retry 4xx, 502, 500, or other 5xx.
 */
export function shouldRetryTanStackQuery(failureCount: number, error: unknown): boolean {
  if (failureCount >= MAX_FAILURE_COUNT_BEFORE_STOP) {
    return false
  }
  if (isLikelyNetworkFailure(error)) {
    return true
  }
  const code = parseHttpStatusFromErrorMessage(errorMessage(error))
  if (code == null) {
    return false
  }
  if (isTransientHttpStatus(code)) {
    return true
  }
  if (code >= 400 && code < 500) {
    return false
  }
  return false
}
