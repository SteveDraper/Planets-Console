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
  connectionKey: 'scope:8,9',
  generation: 1,
  lastEventAt: '2026-07-09T12:00:00.000Z',
  lastEventType: 'row',
  lastConnectResult: null,
} as const

describe('recordClientStreamLifecycle', () => {
  beforeEach(() => {
    useComputeDiagnosticsStore.setState({
      enabled: false,
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

describe('usePerPlayerAnalyticStream freeze hold', () => {
  beforeEach(() => {
    useComputeDiagnosticsStore.setState({
      enabled: false,
      snapshot: null,
      clientStreams: [],
    })
  })

  it('freeze + empty allowlist does not mark rows failed', async () => {
    const connectUntilComplete = vi.fn(async () => 'incomplete_exhausted' as const)
    const policy = makePolicy(connectUntilComplete)

    useComputeDiagnosticsStore.setState({
      enabled: true,
      snapshot: {
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [],
        poolQueue: [],
        dagNodes: [],
        readyQueue: [],
        completionHistory: [],
        serverStreams: [],
        clientStreams: [],
      },
      clientStreams: [],
    })

    const { result } = renderHook(() =>
      usePerPlayerAnalyticStream({
        scope,
        enabled: true,
        playerIdsKey: '3,7,11',
        policy,
      })
    )

    await waitFor(() => {
      expect(result.current.publishedByPlayerId.size).toBe(3)
    })

    expect(connectUntilComplete).not.toHaveBeenCalled()
    for (const playerId of [3, 7, 11]) {
      expect(result.current.publishedByPlayerId.get(playerId)).toEqual({
        status: 'pending',
        detail: null,
      })
    }
    expect(
      useComputeDiagnosticsStore
        .getState()
        .clientStreams.some((entry) => entry.lastConnectResult === 'freeze_held')
    ).toBe(true)
  })

  it('without freeze, incomplete_exhausted still marks rows failed', async () => {
    const connectUntilComplete = vi.fn(async () => 'incomplete_exhausted' as const)
    const policy = makePolicy(connectUntilComplete)

    const { result } = renderHook(() =>
      usePerPlayerAnalyticStream({
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
    expect(connectUntilComplete).toHaveBeenCalled()
  })

  it('disarming freeze reconnects and can complete rows', async () => {
    const connectUntilComplete = vi.fn(
      async (
        _scope: AnalyticShellScope,
        playerIds: number[],
        handlers: {
          signal: AbortSignal
          onEvent: (event: TestEvent) => void
          hasPending: () => boolean
        }
      ) => {
        for (const playerId of playerIds) {
          handlers.onEvent({ type: 'complete', playerId })
        }
        return 'ok' as const
      }
    )
    const policy = makePolicy(connectUntilComplete)

    useComputeDiagnosticsStore.setState({
      enabled: true,
      snapshot: {
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [],
        poolQueue: [],
        dagNodes: [],
        readyQueue: [],
        completionHistory: [],
        serverStreams: [],
        clientStreams: [],
      },
      clientStreams: [],
    })

    const { result } = renderHook(() =>
      usePerPlayerAnalyticStream({
        scope,
        enabled: true,
        playerIdsKey: '3',
        policy,
      })
    )

    await waitFor(() => {
      expect(result.current.publishedByPlayerId.get(3)?.status).toBe('pending')
    })
    expect(connectUntilComplete).not.toHaveBeenCalled()

    await act(async () => {
      useComputeDiagnosticsStore.getState().setSnapshot({
        shell: scope,
        freezeArmed: false,
        allowlistedPlayerIds: [],
        poolQueue: [],
        dagNodes: [],
        readyQueue: [],
        completionHistory: [],
        serverStreams: [],
        clientStreams: [],
      })
    })

    await waitFor(() => {
      expect(result.current.publishedByPlayerId.get(3)?.status).toBe('ok')
    })
    expect(connectUntilComplete).toHaveBeenCalled()
  })

  it('sticky freeze across turn change holds without connecting (stale snapshot shell)', async () => {
    const connectUntilComplete = vi.fn(async () => 'incomplete_exhausted' as const)
    const policy = makePolicy(connectUntilComplete)
    const nextTurnScope: AnalyticShellScope = {
      gameId: '628580',
      turn: 9,
      perspective: 1,
    }

    useComputeDiagnosticsStore.setState({
      enabled: true,
      snapshot: {
        shell: scope,
        freezeArmed: true,
        allowlistedPlayerIds: [3, 7],
        poolQueue: [],
        dagNodes: [],
        readyQueue: [],
        completionHistory: [],
        serverStreams: [],
        clientStreams: [],
      },
      clientStreams: [],
    })

    const { result } = renderHook(() =>
      usePerPlayerAnalyticStream({
        scope: nextTurnScope,
        enabled: true,
        playerIdsKey: '3,7,11',
        policy,
      })
    )

    await waitFor(() => {
      expect(result.current.publishedByPlayerId.size).toBe(3)
    })

    expect(connectUntilComplete).not.toHaveBeenCalled()
    for (const playerId of [3, 7, 11]) {
      expect(result.current.publishedByPlayerId.get(playerId)).toEqual({
        status: 'pending',
        detail: null,
      })
    }
  })
})
