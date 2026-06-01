import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import { DEFAULT_STELLAR_CARTOGRAPHY_MAP_UI_CONFIG } from '../../analytics/mapLayers'
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
  useStellarCartographyMapConfig: vi.fn(() => DEFAULT_STELLAR_CARTOGRAPHY_MAP_UI_CONFIG),
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
  mapQueries: [],
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
    render(<MapShellContent {...defaultProps} cartographyEnabled={false} />)

    expect(useStellarCartographyMapConfig).not.toHaveBeenCalled()
    expect(screen.getByTestId('map-graph')).toBeInTheDocument()
  })

  it('subscribes to live cartography config only when that analytic is enabled', () => {
    render(<MapShellContent {...defaultProps} cartographyEnabled={true} />)

    expect(useStellarCartographyMapConfig).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('map-graph')).toBeInTheDocument()
  })
})
