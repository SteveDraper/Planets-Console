import { beforeEach, describe, expect, it } from 'vitest'
import {
  CLIENT_STREAM_REFRESH_THROTTLE_MS,
  type ClientStreamLifecycle,
  useComputeDiagnosticsStore,
} from './computeDiagnostics'

const BASE_TIME = Date.parse('2026-11-16T12:00:00.000Z')

function entry(overrides: Partial<ClientStreamLifecycle> = {}): ClientStreamLifecycle {
  return {
    streamId: 'scores',
    connectionKey: 'scores:686674:33:21:1,2',
    generation: 1,
    lastEventAt: new Date(BASE_TIME).toISOString(),
    lastEventType: 'solution',
    lastConnectResult: null,
    ...overrides,
  }
}

function at(offsetMs: number): string {
  return new Date(BASE_TIME + offsetMs).toISOString()
}

describe('upsertClientStream throttle', () => {
  beforeEach(() => {
    useComputeDiagnosticsStore.setState({ clientStreams: [] })
  })

  it('skips a same-type refresh inside the throttle window', () => {
    const { upsertClientStream } = useComputeDiagnosticsStore.getState()
    upsertClientStream(entry())
    const before = useComputeDiagnosticsStore.getState().clientStreams

    upsertClientStream(entry({ lastEventAt: at(CLIENT_STREAM_REFRESH_THROTTLE_MS - 1) }))

    expect(useComputeDiagnosticsStore.getState().clientStreams).toBe(before)
  })

  it('records a same-type refresh once the window has passed', () => {
    const { upsertClientStream } = useComputeDiagnosticsStore.getState()
    upsertClientStream(entry())

    upsertClientStream(entry({ lastEventAt: at(CLIENT_STREAM_REFRESH_THROTTLE_MS) }))

    expect(useComputeDiagnosticsStore.getState().clientStreams[0].lastEventAt).toBe(
      at(CLIENT_STREAM_REFRESH_THROTTLE_MS)
    )
  })

  it('always records a new event type, connect result or generation', () => {
    const { upsertClientStream } = useComputeDiagnosticsStore.getState()
    upsertClientStream(entry())

    upsertClientStream(entry({ lastEventAt: at(1), lastEventType: 'complete' }))
    expect(useComputeDiagnosticsStore.getState().clientStreams[0].lastEventType).toBe('complete')

    upsertClientStream(entry({ lastEventAt: at(2), lastEventType: 'complete', lastConnectResult: 'ok' }))
    expect(useComputeDiagnosticsStore.getState().clientStreams[0].lastConnectResult).toBe('ok')

    upsertClientStream(entry({ lastEventAt: at(3), lastEventType: 'complete', lastConnectResult: 'ok', generation: 2 }))
    expect(useComputeDiagnosticsStore.getState().clientStreams[0].generation).toBe(2)
  })

  it('keeps separate rows per connection key', () => {
    const { upsertClientStream } = useComputeDiagnosticsStore.getState()
    upsertClientStream(entry())
    upsertClientStream(entry({ streamId: 'fleet', connectionKey: 'fleet:686674:33:21:1,2', lastEventAt: at(1) }))

    expect(useComputeDiagnosticsStore.getState().clientStreams).toHaveLength(2)
  })
})
