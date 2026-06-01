import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import { STELLAR_CARTOGRAPHY_ANALYTIC_ID } from '../../analytics/mapAnalyticIds'
import { defaultStellarCartographyMapUiConfig } from '../../analytics/stellar-cartography/mapUiConfig'
import { DEFAULT_PLANET_LABEL_OPTIONS } from '../planetMapLabelModel'
import { MapShellContent } from './MapShellContent'
import { useStellarCartographyMapConfig } from '../../lib/useStellarCartographyMapConfig'

vi.mock('../MapGraph', () => ({
  MapGraph: () => <div data-testid="map-graph" />,
}))

vi.mock('../MapPaneWithDisplayControls', () => ({
  MapPaneWithDisplayControls: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}))

vi.mock('../PlanetMapInfoControls', () => ({
  PlanetMapInfoControls: () => null,
}))

vi.mock('../../lib/useStellarCartographyMapConfig', () => ({
  useStellarCartographyMapConfig: vi.fn(() => defaultStellarCartographyMapUiConfig()),
}))

const sampleScope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
}

const displayMapData = {
  nodes: [{ id: 'base-map:1', label: 'A', x: 1, y: 2 }],
  edges: [],
  routeWaypoints: [],
  overlayCircles: [],
  wormholeUnknownEntrances: [],
}

const showingMapShellView = {
  phase: 'showing-map' as const,
  displayMapData,
  showDeferredPending: false,
}

const defaultProps = {
  mapShellView: showingMapShellView,
  enabledMapIds: ['connections'],
  planetLabelOptions: DEFAULT_PLANET_LABEL_OPTIONS,
  onPlanetLabelOptionsChange: vi.fn(),
  onMapZoomChange: vi.fn(),
  onSetZoomReady: vi.fn(),
  analyticScope: sampleScope,
}

describe('MapShellContent cartography config', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('does not subscribe to cartography config when that analytic is disabled', () => {
    render(<MapShellContent {...defaultProps} />)

    expect(useStellarCartographyMapConfig).not.toHaveBeenCalled()
    expect(screen.getByTestId('map-graph')).toBeInTheDocument()
  })

  it('subscribes to live cartography config only when that analytic is enabled', () => {
    render(
      <MapShellContent
        {...defaultProps}
        enabledMapIds={['connections', STELLAR_CARTOGRAPHY_ANALYTIC_ID]}
      />
    )

    expect(useStellarCartographyMapConfig).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('map-graph')).toBeInTheDocument()
  })

  it('renders map errors from mapShellView without query objects', () => {
    const err = new Error('map failed')
    render(
      <MapShellContent
        {...defaultProps}
        mapShellView={{ phase: 'error', error: err }}
      />
    )

    expect(screen.getByText(/Failed to load map data/i)).toBeInTheDocument()
    expect(screen.getByText(/map failed/i)).toBeInTheDocument()
  })
})
