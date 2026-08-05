import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AnalyticShellScope } from '../../api/bff'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { DEFAULT_PLANET_LABEL_OPTIONS } from '../planetMapLabelModel'
import { MapShellContent } from './MapShellContent'

const mapGraphPropsSpy = vi.fn()

vi.mock('../MapGraph', () => ({
  MapGraph: (props: Record<string, unknown>) => {
    mapGraphPropsSpy(props)
    return <div data-testid="map-graph" />
  },
}))

vi.mock('../MapPaneWithDisplayControls', () => ({
  MapPaneWithDisplayControls: ({ children }: { children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}))

vi.mock('../PlanetMapInfoControls', () => ({
  PlanetMapInfoControls: () => null,
}))

const sampleScope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
  username: 'alice',
}

const sampleRoster: readonly PerspectiveRow[] = [
  {
    ordinal: 1,
    playerId: 1,
    name: 'alice',
    raceName: 'Federation',
    eliminationTurn: null,
  },
]

const displayMapData = {
  nodes: [{ id: 'base-map:1', label: 'A', x: 1, y: 2 }],
  edges: [],
  routeWaypoints: [],
  overlayCircles: [],
  regionOverlays: [],
  wormholeUnknownEntrances: [],
  homeworldMarkers: [],
}

function renderShowingMap(
  mapShellView: Parameters<typeof MapShellContent>[0]['mapShellView']
) {
  return render(
    <MapShellContent
      mapShellView={mapShellView}
      analyticScope={sampleScope}
      roster={sampleRoster}
      futureTurnOffset={0}
      planetLabelOptions={DEFAULT_PLANET_LABEL_OPTIONS}
      onPlanetLabelOptionsChange={vi.fn()}
      onMapZoomChange={vi.fn()}
      onSetZoomReady={vi.fn()}
    />
  )
}

describe('MapShellContent', () => {
  it('renders the map graph in showing-map phase', () => {
    renderShowingMap({
      phase: 'showing-map',
      displayMapData,
      showDeferredPending: false,
      displayMapFrameIsLive: true,
    })

    expect(screen.getByTestId('map-graph')).toBeInTheDocument()
  })

  it('forwards shell analyticScope, roster, mapLayersPending, homeworldMapLayerSucceeded, and displayMapFrameIsLive to MapGraph', () => {
    mapGraphPropsSpy.mockClear()
    render(
      <MapShellContent
        mapShellView={{
          phase: 'showing-map',
          displayMapData,
          showDeferredPending: true,
          displayMapFrameIsLive: true,
        }}
        analyticScope={sampleScope}
        roster={sampleRoster}
        homeworldMapLayerSucceeded={true}
        futureTurnOffset={0}
        planetLabelOptions={DEFAULT_PLANET_LABEL_OPTIONS}
        onPlanetLabelOptionsChange={vi.fn()}
        onMapZoomChange={vi.fn()}
        onSetZoomReady={vi.fn()}
      />
    )

    expect(mapGraphPropsSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        analyticScope: sampleScope,
        roster: sampleRoster,
        mapLayersPending: true,
        homeworldMapLayerSucceeded: true,
        displayMapFrameIsLive: true,
      })
    )
  })

  it('forwards displayMapFrameIsLive false when showing a retained frame', () => {
    mapGraphPropsSpy.mockClear()
    renderShowingMap({
      phase: 'showing-map',
      displayMapData,
      showDeferredPending: false,
      displayMapFrameIsLive: false,
    })

    expect(mapGraphPropsSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        displayMapFrameIsLive: false,
        mapLayersPending: false,
      })
    )
  })

  it('defaults homeworldMapLayerSucceeded to false when omitted', () => {
    mapGraphPropsSpy.mockClear()
    renderShowingMap({
      phase: 'showing-map',
      displayMapData,
      showDeferredPending: false,
      displayMapFrameIsLive: true,
    })

    expect(mapGraphPropsSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        homeworldMapLayerSucceeded: false,
      })
    )
  })
  it('shows baseline degraded note when combined map data is degraded', () => {
    renderShowingMap({
      phase: 'showing-map',
      displayMapData: {
        ...displayMapData,
        baselineDegraded: true,
        baselineTurn: 4,
      },
      showDeferredPending: false,
      displayMapFrameIsLive: true,
    })

    expect(screen.getByRole('status')).toHaveTextContent(/Baseline degraded/)
    expect(screen.getByRole('status')).toHaveTextContent(/using turn 4/)
  })

  it('does not show baseline degraded note when not degraded', () => {
    renderShowingMap({
      phase: 'showing-map',
      displayMapData,
      showDeferredPending: false,
      displayMapFrameIsLive: true,
    })

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('renders map errors from mapShellView without query objects', () => {
    const err = new Error('map failed')
    render(
      <MapShellContent
        mapShellView={{ phase: 'error', error: err }}
        analyticScope={sampleScope}
        roster={sampleRoster}
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

  it('shows layer error banner text while map still renders', () => {
    renderShowingMap({
      phase: 'showing-map',
      displayMapData,
      showDeferredPending: false,
      displayMapFrameIsLive: true,
      layerError: new Error(
        'Homeworld locator: turn 59 is not stored (evidence chain requires contiguous turns)'
      ),
    })

    expect(screen.getByTestId('map-graph')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/Homeworld locator/i)
    expect(screen.getByRole('alert')).toHaveTextContent(/turn 59 is not stored/i)
  })

  it('stacks the degraded baseline note and the layer error instead of overlapping them', () => {
    renderShowingMap({
      phase: 'showing-map',
      displayMapData: {
        ...displayMapData,
        baselineDegraded: true,
        baselineTurn: 4,
      },
      showDeferredPending: false,
      displayMapFrameIsLive: true,
      layerError: new Error('Homeworld locator: turn 59 is not stored'),
    })

    const degraded = screen.getByRole('status')
    const layerError = screen.getByRole('alert')
    const stack = screen.getByTestId('map-banner-stack')

    expect(degraded.parentElement).toBe(stack)
    expect(layerError.parentElement).toBe(stack)
    expect(degraded).not.toHaveClass('absolute')
    expect(layerError).not.toHaveClass('absolute')
  })
})
