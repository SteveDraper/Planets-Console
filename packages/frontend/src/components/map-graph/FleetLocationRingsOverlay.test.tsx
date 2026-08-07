import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { FleetLocationRingsOverlay } from './FleetLocationRingsOverlay'
import {
  installPlayerColorsStorePort,
  usePlayerColorsStore,
} from '../../stores/playerColors'
import { defaultColorForPlayerId, resetPlayerColorOverrideStore } from '../../lib/playerColor'
import type { FleetLocationRingStack } from '../../analytics/fleet/fleetLocationRings'

const clientPosRef = vi.hoisted(() => ({
  current: null as { x: number; y: number } | null,
}))

vi.mock('@xyflow/react', () => ({
  useStore: (selector: (state: { domNode: HTMLElement; transform: [number, number, number] }) => unknown) => {
    const domNode = document.createElement('div')
    domNode.getBoundingClientRect = () =>
      ({
        left: 0,
        top: 0,
        right: 800,
        bottom: 600,
        width: 800,
        height: 600,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }) as DOMRect
    return selector({
      domNode,
      transform: [0, 0, 1],
    })
  },
}))

vi.mock('./useOverlayPaneSize', () => ({
  useOverlayPaneSize: () => ({ width: 800, height: 600 }),
}))

vi.mock('./RegionOverlayHoverPanel', () => ({
  useMapPaneClientPos: () => ({
    clientPos: clientPosRef.current,
    domNode: document.createElement('div'),
  }),
}))

function sampleStack(overrides: Partial<FleetLocationRingStack> = {}): FleetLocationRingStack {
  return {
    key: '1000,2000',
    x: 1000,
    y: 2000,
    shipCount: 2,
    hostMilitaryPointsSum: 30,
    strengthFraction: 0.003,
    diameterPx: 10,
    opacity: 0.4,
    strokeWidthPx: 2.5,
    arcs: [
      {
        playerId: 8,
        playerName: 'Alice',
        shipCount: 1,
        share: 0.5,
        ships: [
          {
            recordId: 'a1',
            playerId: 8,
            playerName: 'Alice',
            shipIdLabel: '101',
            hullId: 13,
            hullLabel: 'Cruiser A',
            hostMilitaryPoints: 20,
            x: 1000,
            y: 2000,
          },
        ],
      },
      {
        playerId: 9,
        playerName: 'Bob',
        shipCount: 1,
        share: 0.5,
        ships: [
          {
            recordId: 'b1',
            playerId: 9,
            playerName: 'Bob',
            shipIdLabel: '202',
            hullId: 13,
            hullLabel: 'Cruiser A',
            hostMilitaryPoints: 10,
            x: 1000,
            y: 2000,
          },
        ],
      },
    ],
    ships: [],
    ...overrides,
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('FleetLocationRingsOverlay', () => {
  beforeEach(() => {
    clientPosRef.current = null
    usePlayerColorsStore.setState({ overrides: {} })
    resetPlayerColorOverrideStore()
    installPlayerColorsStorePort()
  })

  it('renders nothing when stacks are empty', () => {
    const { container } = render(
      <FleetLocationRingsOverlay
        stacks={[]}
        planetCoordKeys={new Set()}
        planetLabelsEnabled
      />,
      { wrapper }
    )
    expect(container.querySelector('svg')).toBeNull()
  })

  it('paints arcs and shows standalone tooltip from pane hit-test when not on a planet', async () => {
    const stack = sampleStack()
    // flow center (1000.5, -2000.5) at identity transform
    clientPosRef.current = { x: 1000.5, y: -2000.5 }

    const { container, rerender } = render(
      <FleetLocationRingsOverlay
        stacks={[stack]}
        planetCoordKeys={new Set()}
        planetLabelsEnabled
      />,
      { wrapper }
    )

    // Remount with clientPos already set (hook reads ref each render via mock).
    rerender(
      <FleetLocationRingsOverlay
        stacks={[stack]}
        planetCoordKeys={new Set()}
        planetLabelsEnabled
      />
    )

    const strokes = [...container.querySelectorAll('circle[stroke]')].map((el) =>
      el.getAttribute('stroke')
    )
    expect(strokes).toContain(defaultColorForPlayerId(8))
    expect(strokes).toContain(defaultColorForPlayerId(9))
    expect(container.querySelector('circle.pointer-events-auto')).toBeNull()

    const tooltip = await screen.findByRole('tooltip')
    expect(tooltip.textContent).toMatch(/Alice/)
    expect(tooltip.textContent).toMatch(/Bob/)
    expect(tooltip.textContent).toMatch(/101/)
    expect(tooltip.textContent).toMatch(/202/)
    expect(tooltip.textContent).toMatch(/20 mil/)
    expect(tooltip.textContent).toMatch(/10 mil/)
    expect(tooltip.textContent).not.toMatch(/alibi|possibly/i)
  })

  it('omits standalone tooltip when the stack sits on a planet with labels enabled', () => {
    const stack = sampleStack()
    clientPosRef.current = { x: 1000.5, y: -2000.5 }

    render(
      <FleetLocationRingsOverlay
        stacks={[stack]}
        planetCoordKeys={new Set(['1000,2000'])}
        planetLabelsEnabled
      />,
      { wrapper }
    )

    expect(screen.queryByRole('tooltip')).toBeNull()
  })

  it('re-paints arc strokes when a player color override changes', () => {
    const { container } = render(
      <FleetLocationRingsOverlay
        stacks={[sampleStack()]}
        planetCoordKeys={new Set()}
        planetLabelsEnabled={false}
      />,
      { wrapper }
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
