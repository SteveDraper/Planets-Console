import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { FleetLocationRingsOverlay } from './FleetLocationRingsOverlay'
import { FleetStreamPlayersProvider } from '../../analytics/fleet/FleetStreamPlayersContext'
import type { FleetPlayerStreamSlice } from '../../analytics/fleet/fleetTablePlayerStreamState'
import { seedShellViewpoint } from '../../analytics/fleet/fleetTestShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import {
  installPlayerColorsStorePort,
  usePlayerColorsStore,
} from '../../stores/playerColors'
import { useShellStore } from '../../stores/shell'
import { defaultColorForPlayerId, resetPlayerColorOverrideStore } from '../../lib/playerColor'

vi.mock('@xyflow/react', () => ({
  useStore: (selector: (state: { domNode: HTMLElement; transform: [number, number, number] }) => unknown) =>
    selector({
      domNode: document.createElement('div'),
      transform: [0, 0, 1],
    }),
}))

vi.mock('./useOverlayPaneSize', () => ({
  useOverlayPaneSize: () => ({ width: 800, height: 600 }),
}))

vi.mock('../../api/bff', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../api/bff')>()
  return {
    ...actual,
    fetchFleetComponentCatalog: vi.fn().mockResolvedValue({
      hulls: { '13': 'Cruiser A' },
      engines: {},
      beams: {},
      torpedoes: {},
    }),
  }
})

const scope: AnalyticShellScope = {
  gameId: '628580',
  turn: 9,
  perspective: 1,
}

function createWrapper(
  client: QueryClient,
  streamPlayersById: Map<number, FleetPlayerStreamSlice> = new Map()
) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <FleetStreamPlayersProvider streamPlayersById={streamPlayersById}>
          {children}
        </FleetStreamPlayersProvider>
      </QueryClientProvider>
    )
  }
}

function stackedStreamPlayersById(): Map<number, FleetPlayerStreamSlice> {
  return new Map<number, FleetPlayerStreamSlice>([
    [
      8,
      {
        playerName: 'Alice',
        records: [
          {
            recordId: 'a1',
            disposition: 'active',
            qualifiers: {
              possiblyLost: { sinceTurn: 7, source: 'scoreboard' },
              alibi: { afterTurn: 7, sightingTurn: 9, source: 'turnInfo.ships' },
            },
            fields: {
              shipId: { kind: 'known', value: 101 },
              hull: { kind: 'known', value: 13 },
              engine: { kind: 'unknown' },
              beams: { kind: 'unknown' },
              launchers: { kind: 'unknown' },
              builtTurn: { kind: 'unknown' },
              location: { kind: 'unknown' },
            },
            buildOptionSets: [],
            lastSeen: { turn: 9, x: 1000, y: 2000 },
            militaryEstimate2x: 40,
          },
        ],
        discrepancyOverlay: 'inherit',
        isComplete: true,
        isFinal: true,
        isPending: false,
        summary: 'ok',
        error: null,
      },
    ],
    [
      9,
      {
        playerName: 'Bob',
        records: [
          {
            recordId: 'b1',
            disposition: 'active',
            qualifiers: {},
            fields: {
              shipId: { kind: 'known', value: 202 },
              hull: { kind: 'known', value: 13 },
              engine: { kind: 'unknown' },
              beams: { kind: 'unknown' },
              launchers: { kind: 'unknown' },
              builtTurn: { kind: 'unknown' },
              location: { kind: 'unknown' },
            },
            buildOptionSets: [],
            lastSeen: { turn: 9, x: 1000, y: 2000 },
            militaryEstimate2x: 20,
          },
        ],
        discrepancyOverlay: 'inherit',
        isComplete: true,
        isFinal: true,
        isPending: false,
        summary: 'ok',
        error: null,
      },
    ],
  ])
}

describe('FleetLocationRingsOverlay', () => {
  beforeEach(() => {
    useFleetPlayerVisibilityStore.setState({ overrides: {} })
    usePlayerColorsStore.setState({ overrides: {} })
    resetPlayerColorOverrideStore()
    installPlayerColorsStorePort()
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

  it('renders nothing when disabled', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <FleetLocationRingsOverlay analyticScope={scope} enabled={false} />,
      { wrapper: createWrapper(client) }
    )
    expect(container.querySelector('svg')).toBeNull()
  })

  it('paints stacked arcs and shows hull/mil tooltip without alibi or possibly-lost', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const streamPlayersById = stackedStreamPlayersById()

    const { container } = render(
      <FleetLocationRingsOverlay analyticScope={scope} enabled />,
      { wrapper: createWrapper(client, streamPlayersById) }
    )

    const strokes = [...container.querySelectorAll('circle[stroke]')].map((el) =>
      el.getAttribute('stroke')
    )
    expect(strokes).toContain(defaultColorForPlayerId(8))
    expect(strokes).toContain(defaultColorForPlayerId(9))

    const hit = container.querySelector('circle.pointer-events-auto')
    expect(hit).not.toBeNull()
    fireEvent.mouseEnter(hit!)

    const tooltip = await screen.findByRole('tooltip')
    expect(tooltip).toBeInTheDocument()
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('Bob')).toBeInTheDocument()
    expect(tooltip.textContent).toMatch(/101/)
    expect(tooltip.textContent).toMatch(/202/)
    expect(tooltip.textContent).toMatch(/20 mil/)
    expect(tooltip.textContent).toMatch(/10 mil/)
    expect(tooltip.textContent).not.toMatch(/alibi|possibly/i)
  })

  it('re-paints arc strokes when a player color override changes', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { container } = render(
      <FleetLocationRingsOverlay analyticScope={scope} enabled />,
      { wrapper: createWrapper(client, stackedStreamPlayersById()) }
    )

    expect(
      [...container.querySelectorAll('circle[stroke]')].map((el) => el.getAttribute('stroke'))
    ).toContain(defaultColorForPlayerId(8))

    act(() => {
      usePlayerColorsStore.getState().setPlayerColorOverride(8, '#112233')
    })

    expect(
      [...container.querySelectorAll('circle[stroke]')].map((el) => el.getAttribute('stroke'))
    ).toContain('#112233')
  })
})
