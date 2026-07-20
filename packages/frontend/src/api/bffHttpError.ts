/**
 * Typed BFF HTTP failure that preserves status (used for mid-session auth handling).
 */

/** Human-readable endpoint for error rows (method + path, no host). */
export function withEndpointIfGeneric(message: string, endpointLabel: string): string {
  const detail = message.trim()
  if (!isGenericServerErrorMessage(detail)) {
    return detail || 'Request failed'
  }
  if (detail.includes(endpointLabel)) {
    return detail || 'Request failed'
  }
  const base = detail || 'Request failed'
  return `${base} (${endpointLabel})`
}

export function isGenericServerErrorMessage(message: string): boolean {
  const t = message.trim().toLowerCase()
  if (t === '') {
    return true
  }
  if (t === 'internal server error') {
    return true
  }
  if (t === 'bad gateway') {
    return true
  }
  if (t === 'service unavailable') {
    return true
  }
  if (t === 'gateway timeout') {
    return true
  }
  // Response body or fallback was only an HTTP status code for a server error
  if (/^5\d\d$/.test(t)) {
    return true
  }
  return false
}

export class BffHttpError extends Error {
  readonly status: number
  readonly detail: string
  readonly endpointLabel: string

  constructor(status: number, detail: string, endpointLabel: string) {
    super(withEndpointIfGeneric(detail, endpointLabel))
    this.name = 'BffHttpError'
    this.status = status
    this.detail = detail
    this.endpointLabel = endpointLabel
  }
}

/** True when a BFF failure is credential-required (HTTP 401). */
export function isCredentialRequiredError(err: unknown): boolean {
  return err instanceof BffHttpError && err.status === 401
}

export function throwBffHttpError(
  status: number,
  detail: string,
  endpointLabel: string
): never {
  throw new BffHttpError(status, detail, endpointLabel)
}

/** Read JSON `detail` from a non-OK Response and throw {@link BffHttpError}. */
export async function throwBffHttpErrorFromResponse(
  r: Response,
  endpointLabel: string
): Promise<never> {
  let detail = r.statusText
  try {
    const j: { detail?: string | unknown } = await r.json()
    if (j?.detail != null) {
      detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)
    }
  } catch {
    /* use statusText */
  }
  throwBffHttpError(r.status, detail, endpointLabel)
}
