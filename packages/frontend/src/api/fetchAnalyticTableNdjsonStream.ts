import type { BffRequestTarget } from './bffSend'
import { readNdjsonStream } from './readNdjsonStream'

type BffRequestFn = (
  target: BffRequestTarget,
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
  route: BffRequestTarget,
  queryParams: URLSearchParams,
  parseLine: (line: string) => T | null,
  handlers: AnalyticTableNdjsonStreamHandlers<T>
): Promise<void> {
  const qs = `?${queryParams.toString()}`
  const endpointLabel = `GET ${route.path}`
  const r = await bffRequest(
    { path: `${route.path}${qs}`, gameId: route.gameId },
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
