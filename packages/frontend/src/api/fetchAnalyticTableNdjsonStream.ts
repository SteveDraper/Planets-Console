import { readNdjsonStream } from './readNdjsonStream'

type BffRequestFn = (
  path: string,
  init: RequestInit | undefined,
  endpointLabel: string
) => Promise<Response>

type WithEndpointFn = (message: string, endpointLabel: string) => string

export type AnalyticTableNdjsonStreamHandlers<T> = {
  signal?: AbortSignal
  onEvent: (event: T) => void
}

export async function fetchAnalyticTableNdjsonStream<T>(
  bffRequest: BffRequestFn,
  withEndpoint: WithEndpointFn,
  path: string,
  queryParams: URLSearchParams,
  parseLine: (line: string) => T | null,
  handlers: AnalyticTableNdjsonStreamHandlers<T>
): Promise<void> {
  const qs = `?${queryParams.toString()}`
  const endpointLabel = `GET ${path}`
  const r = await bffRequest(
    `${path}${qs}`,
    { signal: handlers.signal, cache: 'no-store' },
    endpointLabel
  )
  if (!r.ok) {
    throw new Error(withEndpoint(String(r.status), endpointLabel))
  }
  if (!r.body) {
    throw new Error(withEndpoint('No response body', endpointLabel))
  }

  await readNdjsonStream(r.body, (line) => {
    const event = parseLine(line)
    if (event) {
      handlers.onEvent(event)
    }
  })
}
