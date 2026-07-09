import { beforeEach, describe, expect, it } from 'vitest'
import { useComputeDiagnosticsStore } from '../stores/computeDiagnostics'
import { recordClientStreamLifecycle } from './usePerPlayerAnalyticStream'

const sampleEntry = {
  connectionKey: 'scope:8,9',
  generation: 1,
  lastEventAt: '2026-07-09T12:00:00.000Z',
  lastEventType: 'row',
  lastConnectResult: null,
} as const

describe('recordClientStreamLifecycle', () => {
  beforeEach(() => {
    useComputeDiagnosticsStore.setState({ enabled: false, clientStreams: [] })
  })

  it('does not upsert when compute diagnostics are disabled', () => {
    recordClientStreamLifecycle(sampleEntry)
    expect(useComputeDiagnosticsStore.getState().clientStreams).toEqual([])
  })

  it('upserts when compute diagnostics are enabled', () => {
    useComputeDiagnosticsStore.getState().setEnabled(true)
    recordClientStreamLifecycle(sampleEntry)
    expect(useComputeDiagnosticsStore.getState().clientStreams).toEqual([sampleEntry])
  })
})
