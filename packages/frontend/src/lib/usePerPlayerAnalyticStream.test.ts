import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../api/bff'
import { useComputeDiagnosticsStore } from '../stores/computeDiagnostics'
import {
  recordClientStreamLifecycle,
  usePerPlayerAnalyticStream,
  type PerPlayerAnalyticStreamPolicy,
} from './usePerPlayerAnalyticStream'

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 8,
  perspective: 1,
}

type TestEvent = { type: string; playerId?: number | null; detail?: string }
type TestRef = { complete: boolean; failed: boolean; detail: string | null }
type TestPublished = { status: 'pending' | 'ok' | 'failed'; detail: string | null }

function makePolicy(
  connectUntilComplete: PerPlayerAnalyticStreamPolicy<
    TestEvent,
    TestRef,
    TestPublished
  >['connectUntilComplete']
): PerPlayerAnalyticStreamPolicy<TestEvent, TestRef, TestPublished> {
  return {
    initialRefState: () => ({ complete: false, failed: false, detail: null }),
    reduceRefState: (current, event) => {
      if (event.type === 'complete') {
        return { complete: true, failed: false, detail: null }
      }
      if (event.type === 'error') {
        return { complete: true, failed: true, detail: event.detail ?? 'error' }
      }
      return current
    },
    isRefStateComplete: (state) => state.complete,
    publishedFromRefState: (_playerId, state) => {
      if (state.failed) {
        return { status: 'failed', detail: state.detail }
      }
      if (state.complete) {
        return { status: 'ok', detail: null }
      }
      return { status: 'pending', detail: null }
    },
    seedPublishedOnNewConnection: (playerIds) => {
      const seeded = new Map<number, TestPublished>()
      for (const playerId of playerIds) {
        seeded.set(playerId, { status: 'pending', detail: null })
      }
      return seeded
    },
    streamFailureEvent: (playerId, summary) => ({
      type: 'error',
      playerId,
      detail: summary,
    }),
    connectUntilComplete,
    incompleteExhaustedMessage: 'stream ended incomplete',
  }
}

const sampleEntry = {
  streamId: 'test',
  connectionKey: 'test:scope:8,9',
  generation: 1,
  lastEventAt: '2026-07-09T12:00:00.000Z',
  lastEventType: 'row',
  lastConnectResult: null,
} as const

describe('recordClientStreamLifecycle', () => {
  beforeEach(() => {
    useComputeDiagnosticsStore.setState({
      enabled: false,
      freezeStatus: null,
      snapshot: null,
      clientStreams: [],
    })
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

describe('usePerPlayerAnalyticStream under compute diagnostics freeze', () => {
  beforeEach(() => {
    useComputeDiagnosticsStore.setState({
      enabled: true,
      freezeStatus: {
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [],
      },
      snapshot: null,
      clientStreams: [],
    })
  })

  it('subscribes every player even with an empty focus allowlist', async () => {
    const connectUntilComplete = vi.fn(
      (_scope: AnalyticShellScope, _playerIds: number[]) =>
        new Promise<'ok'>(() => {})
    )
    const policy = makePolicy(connectUntilComplete)

    const { result } = renderHook(() =>
      usePerPlayerAnalyticStream({
        streamId: 'test',
        scope,
        enabled: true,
        playerIdsKey: '3,7,11',
        policy,
      })
    )

    await waitFor(() => {
      expect(connectUntilComplete).toHaveBeenCalledTimes(1)
    })
    expect(connectUntilComplete.mock.calls[0][1]).toEqual([3, 7, 11])
    for (const playerId of [3, 7, 11]) {
      expect(result.current.publishedByPlayerId.get(playerId)).toEqual({
        status: 'pending',
        detail: null,
      })
    }
  })

  it('does not reconnect when the freeze status changes', async () => {
    const connectUntilComplete = vi.fn(
      (_scope: AnalyticShellScope, _playerIds: number[]) =>
        new Promise<'ok'>(() => {})
    )
    const policy = makePolicy(connectUntilComplete)

    renderHook(() =>
      usePerPlayerAnalyticStream({
        streamId: 'test',
        scope,
        enabled: true,
        playerIdsKey: '3,7',
        policy,
      })
    )
    await waitFor(() => {
      expect(connectUntilComplete).toHaveBeenCalledTimes(1)
    })

    act(() => {
      useComputeDiagnosticsStore.getState().setFreezeStatus({
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [3],
      })
    })

    expect(connectUntilComplete).toHaveBeenCalledTimes(1)
  })

  it('marks rows failed when the stream ends incomplete', async () => {
    const connectUntilComplete = vi.fn(async () => 'incomplete_exhausted' as const)
    const policy = makePolicy(connectUntilComplete)

    const { result } = renderHook(() =>
      usePerPlayerAnalyticStream({
        streamId: 'test',
        scope,
        enabled: true,
        playerIdsKey: '3,7',
        policy,
      })
    )

    await waitFor(() => {
      expect(result.current.publishedByPlayerId.get(3)?.status).toBe('failed')
    })
    expect(result.current.publishedByPlayerId.get(7)?.status).toBe('failed')
  })
})

describe('usePerPlayerAnalyticStream client stream rows', () => {
  beforeEach(() => {
    useComputeDiagnosticsStore.setState({
      enabled: true,
      freezeStatus: null,
      snapshot: null,
      clientStreams: [],
    })
  })

  it('keeps separate clientStreams rows for different streamIds', async () => {
    const connectUntilComplete = vi.fn(async () => 'ok' as const)
    const policy = makePolicy(connectUntilComplete)

    renderHook(() => {
      usePerPlayerAnalyticStream({
        streamId: 'fleet',
        scope,
        enabled: true,
        playerIdsKey: '3,7',
        policy,
      })
      usePerPlayerAnalyticStream({
        streamId: 'scores',
        scope,
        enabled: true,
        playerIdsKey: '3,7',
        policy,
      })
    })

    await waitFor(() => {
      const streams = useComputeDiagnosticsStore.getState().clientStreams
      expect(streams).toHaveLength(2)
    })

    const streams = useComputeDiagnosticsStore.getState().clientStreams
    const byStreamId = Object.fromEntries(streams.map((entry) => [entry.streamId, entry]))
    expect(byStreamId.fleet?.connectionKey.startsWith('fleet:')).toBe(true)
    expect(byStreamId.scores?.connectionKey.startsWith('scores:')).toBe(true)
  })
})
