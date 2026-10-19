import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import * as bff from '../../api/bff'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { useShellStore } from '../../stores/shell'
import { seedShellViewpoint } from './fleetTestShell'
import type { FleetTableRecord } from './fleetTableWireSchema'
import { useFleetHoverAdmissionStream } from './useFleetHoverAdmissionStream'
import { useFleetTableStream } from './useFleetTableStream'

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
    shipId: { kind: 'known', value: 1 },
    hull: { kind: 'known', value: 13 },
    engine: { kind: 'unknown' },
    beams: { kind: 'unknown' },
    launchers: { kind: 'unknown' },
    builtTurn: { kind: 'unknown' },
    location: { kind: 'unknown' },
  },
  buildOptionSets: [],
  lastSeen: { turn: 111, x: 10, y: 20 },
}

function createWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

describe('useFleetHoverAdmissionStream', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: { '9': false } })
    useShellStore.setState({
      selectedGameId: null,
      gameInfoContext: null,
      selectedTurn: null,
      perspectiveOverrideOrdinal: null,
      storageOnlyLoad: false,
      storageAvailablePerspectives: null,
    })
    seedShellViewpoint(1)
  })

  it('admits a visibility-off player without aborting the fleet stream', async () => {
    const calls: { playerIds: number[]; signal: AbortSignal }[] = []

    vi.spyOn(bff, 'fetchFleetTableStream').mockImplementation(
      async (_scope, playerIds, handlers) => {
        const signal = handlers.signal!
        calls.push({ playerIds: [...playerIds], signal })
        for (const playerId of playerIds) {
          handlers.onEvent({
            type: 'ledger_updated',
            playerId,
            ledger: {
              playerId,
              playerName: `Player ${playerId}`,
              records: [refinedRecord],
            },
          })
          handlers.onEvent({
            type: 'complete',
            playerId,
            isFinal: true,
            summary: `done ${playerId}`,
          })
        }
        await new Promise<void>((resolve) => {
          signal.addEventListener('abort', () => resolve())
        })
      }
    )

    const initialProps: { hoverPlayerId: number | null } = { hoverPlayerId: null }
    const { result, rerender } = renderHook(
      ({ hoverPlayerId }: { hoverPlayerId: number | null }) => {
        const main = useFleetTableStream(scope, true)
        const hoverSlice = useFleetHoverAdmissionStream(scope, hoverPlayerId)
        return { main: main.streamPlayersById, hoverSlice }
      },
      { initialProps, wrapper: createWrapper() }
    )

    await waitFor(() => {
      expect(result.current.main.get(8)?.records).toEqual([refinedRecord])
    })

    const mainCall = calls.find((call) => call.playerIds.includes(8))
    expect(mainCall).toBeDefined()
    expect(calls.some((call) => call.playerIds.includes(9))).toBe(false)

    rerender({ hoverPlayerId: 9 })

    await waitFor(() => {
      expect(result.current.hoverSlice?.records).toEqual([refinedRecord])
    })

    expect(mainCall!.signal.aborted).toBe(false)
    expect(result.current.main.get(8)?.records).toEqual([refinedRecord])
    expect(
      calls.filter((call) => call.playerIds.length === 1 && call.playerIds[0] === 9)
    ).toHaveLength(1)
    expect(result.current.main.has(9)).toBe(false)
  })
})
