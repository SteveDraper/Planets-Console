const BFF_BASE = '' // proxy in dev: /bff -> backend

/** When set in `sessionStorage`, all `/bff/...` requests get `?includeDiagnostics=true` (or `&...`). */
export const INCLUDE_DIAGNOSTICS_SESSION_KEY = 'planetsConsole.includeDiagnostics' as const

export function isIncludeDiagnosticsSessionEnabled(): boolean {
  if (typeof sessionStorage === 'undefined') {
    return false
  }
  return sessionStorage.getItem(INCLUDE_DIAGNOSTICS_SESSION_KEY) === '1'
}

export function setIncludeDiagnosticsSessionEnabled(enabled: boolean): void {
  if (typeof sessionStorage === 'undefined') {
    return
  }
  if (enabled) {
    sessionStorage.setItem(INCLUDE_DIAGNOSTICS_SESSION_KEY, '1')
  } else {
    sessionStorage.removeItem(INCLUDE_DIAGNOSTICS_SESSION_KEY)
  }
}

function appendIncludeDiagnosticsQuery(path: string): string {
  if (!path.startsWith('/bff/')) {
    return path
  }
  if (!isIncludeDiagnosticsSessionEnabled()) {
    return path
  }
  if (/[?&]includeDiagnostics=/.test(path)) {
    return path
  }
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}includeDiagnostics=true`
}

/**
 * When `fetch` rejects (no HTTP response), browsers often set only a generic
 * "Failed to fetch" / "Load failed" message. This keeps the original text but
 * adds method+path, the request URL path, and `cause` when present.
 */
export function toFetchRejectionError(
  err: unknown,
  endpointLabel: string,
  attemptedPath: string
): Error {
  const name = err instanceof Error ? err.name : 'Error'
  const message = err instanceof Error ? err.message : String(err)
  let cause = ''
  if (err instanceof Error && 'cause' in err) {
    const c = (err as Error & { cause?: unknown }).cause
    if (c != null) {
      cause = `; cause: ${String(c)}`
    }
  }
  return new Error(
    `${name}: ${message} — ${endpointLabel} (request: ${attemptedPath}). ` +
      `No HTTP response${cause}. ` +
      `Check BFF is running, the dev proxy targets it, and there is no CORS or connection problem.`
  )
}

/**
 * One BFF request: its path (with any query string) and the game it names in its path, query or
 * body. `gameId` is null only for a request that names no game.
 */
export type BffRequestTarget = {
  path: string
  gameId: string | null
}

/**
 * Send one BFF request now, without waiting for a pending Backfill walk stop. Only the stop
 * itself sends this way; every other request goes through `bffRequest` in `bff.ts`.
 */
export async function sendBffRequest(
  path: string,
  init: RequestInit | undefined,
  endpointLabel: string
): Promise<Response> {
  const requestPath = appendIncludeDiagnosticsQuery(path)
  const url = `${BFF_BASE}${requestPath}`
  try {
    return await fetch(url, init)
  } catch (e) {
    throw toFetchRejectionError(e, endpointLabel, requestPath)
  }
}
