import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { FleetHeadingTrailsOverlay } from './FleetHeadingTrailsOverlay'
import {
  installPlayerColorsStorePort,
  resetPlayerColorsStoreState,
  usePlayerColorsStore,
} from '../../stores/playerColors'
import { defaultColorForPlayerId, resetPlayerColorResolutionPort } from '../../lib/playerColor'
import type { FleetHeadingTrail } from '../../analytics/fleet/fleetHeadingTrails'
import { FLEET_HEADING_TRAIL_CURRENT_OPACITY } from '../../analytics/fleet/fleetHeadingTrails'

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

function sampleTrail(overrides: Partial<FleetHeadingTrail> = {}): FleetHeadingTrail {
  return {
    key: 'r1:1000,2000',
    recordId: 'r1',
    playerId: 8,
    x: 1000,
    y: 2000,
    endX: 1081,
    endY: 2000,
    heading: 90,
    travelLyPerTurn: 81,
    opacity: FLEET_HEADING_TRAIL_CURRENT_OPACITY,
    ...overrides,
  }
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>
}

describe('FleetHeadingTrailsOverlay', () => {
  beforeEach(() => {
    resetPlayerColorsStoreState({
      diplomacyThreshold: 2,
    })
    resetPlayerColorResolutionPort()
    installPlayerColorsStorePort()
  })

  it('renders nothing when trails are empty', () => {
    const { container } = render(<FleetHeadingTrailsOverlay trails={[]} />, { wrapper })
    expect(container.querySelector('svg')).toBeNull()
  })

  it('paints player-colored rays without pointer capture', () => {
    const { container } = render(
      <FleetHeadingTrailsOverlay
        trails={[sampleTrail(), sampleTrail({ key: 'r2:1000,2000', recordId: 'r2', playerId: 9 })]}
      />,
      { wrapper }
    )

    const strokes = [...container.querySelectorAll('line[stroke]')].map((el) =>
      el.getAttribute('stroke')
    )
    expect(strokes).toContain(defaultColorForPlayerId(8))
    expect(strokes).toContain(defaultColorForPlayerId(9))
    expect(container.querySelector('line.pointer-events-auto')).toBeNull()
    expect(container.querySelector('[role="tooltip"]')).toBeNull()
  })

  it('re-paints when a player color override changes', () => {
    const { container } = render(
      <FleetHeadingTrailsOverlay trails={[sampleTrail()]} />,
      { wrapper }
    )

    expect(
      [...container.querySelectorAll('line[stroke]')].map((el) => el.getAttribute('stroke'))
    ).toContain(defaultColorForPlayerId(8))

    act(() => {
      usePlayerColorsStore.getState().setPlayerColorOverride(8, '#112233')
    })

    expect(
      [...container.querySelectorAll('line[stroke]')].map((el) => el.getAttribute('stroke'))
    ).toContain('#112233')
  })
})
