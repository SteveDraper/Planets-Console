import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DEFAULT_PLANET_LABEL_OPTIONS } from '../planetMapLabelModel'
import { MapShellContent } from './MapShellContent'

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

const displayMapData = {
  nodes: [{ id: 'base-map:1', label: 'A', x: 1, y: 2 }],
  edges: [],
  routeWaypoints: [],
  overlayCircles: [],
  wormholeUnknownEntrances: [],
}

describe('MapShellContent', () => {
  it('renders the map graph in showing-map phase', () => {
    render(
      <MapShellContent
        mapShellView={{
          phase: 'showing-map',
          displayMapData,
          showDeferredPending: false,
        }}
        futureTurnOffset={0}
        planetLabelOptions={DEFAULT_PLANET_LABEL_OPTIONS}
        onPlanetLabelOptionsChange={vi.fn()}
        onMapZoomChange={vi.fn()}
        onSetZoomReady={vi.fn()}
      />
    )

    expect(screen.getByTestId('map-graph')).toBeInTheDocument()
  })

  it('renders map errors from mapShellView without query objects', () => {
    const err = new Error('map failed')
    render(
      <MapShellContent
        mapShellView={{ phase: 'error', error: err }}
        futureTurnOffset={0}
        planetLabelOptions={DEFAULT_PLANET_LABEL_OPTIONS}
        onPlanetLabelOptionsChange={vi.fn()}
        onMapZoomChange={vi.fn()}
        onSetZoomReady={vi.fn()}
      />
    )

    expect(screen.getByText(/Failed to load map data/i)).toBeInTheDocument()
    expect(screen.getByText(/map failed/i)).toBeInTheDocument()
  })
})
