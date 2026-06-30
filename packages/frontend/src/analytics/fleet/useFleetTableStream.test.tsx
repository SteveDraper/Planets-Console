import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import * as bff from '../../api/bff'
import type { FleetTableStreamEvent } from '../../api/fleetTableStreamEventSchema'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'
import { seedShellViewpoint } from './fleetTestShell'
import { useFleetTableStream } from './useFleetTableStream'
import type { FleetTableRecord } from './fleetTableWireSchema'

type StreamHandlers = Parameters<typeof bff.fetchFleetTableStream>[2]

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 111,
  perspective: 1,
}

const refinedRecord: FleetTableRecord = {
  recordId: 'rec-active',
  disposition: 'active',
  qualifiers: {},
  fields: {
    shipId: { kind: 'bounded', operator: 'lte', value: 318 },
    hull: { kind: 'known', value: 13 },
    engine: { kind: 'known', value: 9 },
    beams: { kind: 'options', values: [3, 5] },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'known', value: 4 },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [
    {
      comboId: 'combo_a',
      label: 'Option A',
      solutionRankWeight: 10,
      hullId: 13,
      engineId: 9,
      beamId: 3,
      beamCount: 8,
      launcherCount: 6,
      torpId: 6,
    },
  ],
}

describe('useFleetTableStream', () => {
  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideName: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
    seedShellViewpoint('Alice')
  })

  it('updates visible players independently from stream events', async () => {
    vi.spyOn(bff, 'fetchFleetTableStream').mockImplementation(
      async (_scope, _playerIds, handlers) => {
        handlers.onEvent({
          type: 'ledger_updated',
          playerId: 8,
          ledger: {
            playerId: 8,
            playerName: 'Alice',
            records: [refinedRecord],
          },
        })
        handlers.onEvent({
          type: 'complete',
          playerId: 8,
          isFinal: true,
          summary: 'Player 8 ok',
        })
        handlers.onEvent({
          type: 'error',
          playerId: 9,
          detail: '502 player 9 failed',
        })
      }
    )

    const { result } = renderHook(() => useFleetTableStream(scope, true))

    await waitFor(() => {
      expect(result.current.streamPlayersById.get(8)?.records).toEqual([refinedRecord])
      expect(result.current.streamPlayersById.get(9)?.error).toContain('502')
    })
  })

  it('reconnects when visible player ids change', async () => {
    let streamCallCount = 0

    vi.spyOn(bff, 'fetchFleetTableStream').mockImplementation(
      async (_scope, playerIds, handlers) => {
        streamCallCount += 1
        for (const playerId of playerIds) {
          handlers.onEvent({
            type: 'complete',
            playerId,
            isFinal: true,
            summary: `done ${playerId}`,
          })
        }
        await new Promise<void>((resolve) => {
          handlers.signal?.addEventListener('abort', () => {
            resolve()
          })
        })
      }
    )

    const { rerender } = renderHook(
      ({ enabled }) => useFleetTableStream(scope, enabled),
      { initialProps: { enabled: true } }
    )

    await waitFor(() => {
      expect(streamCallCount).toBe(1)
    })

    act(() => {
      useFleetPlayerVisibilityStore.getState().setFleetPlayerVisible(9, false)
    })
    rerender({ enabled: true })

    await waitFor(() => {
      expect(streamCallCount).toBeGreaterThanOrEqual(2)
    })
  })

  it('does not connect when disabled', () => {
    const fetchSpy = vi.spyOn(bff, 'fetchFleetTableStream').mockResolvedValue()

    renderHook(() => useFleetTableStream(scope, false))

    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
