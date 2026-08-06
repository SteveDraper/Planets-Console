import { useEffect, useState } from 'react'
import { homeworldBaselineDegradedMessage } from '../../analytics/homeworld-locator/constants'
import type { AnalyticShellScope } from '../../api/bff'
import type { FleetPlayerStreamSlice } from '../../analytics/fleet/fleetTablePlayerStreamState'
import type { StellarCartographyMapContext } from '../../analytics/stellar-cartography/mapUiConfig'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import { MapGraph } from '../MapGraph'
import { MapPaneWithDisplayControls } from '../MapPaneWithDisplayControls'
import { PlanetMapInfoControls } from '../PlanetMapInfoControls'
import type { PlanetLabelOptions } from '../planetMapLabelModel'
import { ShellCenterPane, ShellErrorPane } from './ShellPlaceholders'
import type { MapShellView } from '../../lib/mapDisplayRetention'

export type MapShellContentProps = {
  mapShellView: MapShellView
  /** Shell-derived scope already owned by MapMainArea; forwarded to map feature menus. */
  analyticScope: AnalyticShellScope
  /** Game roster for homeworld ownership menu labels; owned at the shell boundary. */
  roster: readonly PerspectiveRow[]
  /**
   * Homeworld map query ``isSuccess`` from shell map queries; gates region materialize.
   * Defaults false so missing wiring cannot consume init-only ``all`` on empty overlays.
   */
  homeworldMapLayerSucceeded?: boolean
  /** Turns beyond latest stored game turn; applied at cartography display time. */
  futureTurnOffset: number
  planetLabelOptions: PlanetLabelOptions
  onPlanetLabelOptionsChange: (value: PlanetLabelOptions) => void
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  cartography?: StellarCartographyMapContext
  /** Shared fleet stream demux state for location rings (view-mode-independent). */
  fleetStreamPlayersById?: ReadonlyMap<number, FleetPlayerStreamSlice>
}

/** Renders map shell phases (loading, error, or live map with optional deferred pending banner). */
export function MapShellContent({
  mapShellView,
  analyticScope,
  roster,
  homeworldMapLayerSucceeded = false,
  futureTurnOffset,
  planetLabelOptions,
  onPlanetLabelOptionsChange,
  onMapZoomChange,
  onSetZoomReady,
  cartography,
  fleetStreamPlayersById,
}: MapShellContentProps) {
  switch (mapShellView.phase) {
    case 'full-loading':
      return <ShellCenterPane message={mapShellView.loadingMessage} />
    case 'error':
      return (
        <ShellErrorPane
          title="Failed to load map data"
          error={mapShellView.error}
          fallbackDetail="Failed to load map data"
        />
      )
    case 'showing-map':
      return (
        <MapShellShowingMap
          mapShellView={mapShellView}
          analyticScope={analyticScope}
          roster={roster}
          homeworldMapLayerSucceeded={homeworldMapLayerSucceeded}
          futureTurnOffset={futureTurnOffset}
          planetLabelOptions={planetLabelOptions}
          onPlanetLabelOptionsChange={onPlanetLabelOptionsChange}
          onMapZoomChange={onMapZoomChange}
          onSetZoomReady={onSetZoomReady}
          cartography={cartography}
          fleetStreamPlayersById={fleetStreamPlayersById}
        />
      )
  }
}

function MapShellShowingMap({
  mapShellView,
  analyticScope,
  roster,
  homeworldMapLayerSucceeded = false,
  futureTurnOffset,
  planetLabelOptions,
  onPlanetLabelOptionsChange,
  onMapZoomChange,
  onSetZoomReady,
  cartography,
  fleetStreamPlayersById,
}: MapShellContentProps & { mapShellView: Extract<MapShellView, { phase: 'showing-map' }> }) {
  return (
    <main className="relative flex min-h-0 flex-1 flex-col bg-black">
      <MapPaneWithDisplayControls
        controls={
          <PlanetMapInfoControls
            value={planetLabelOptions}
            onChange={onPlanetLabelOptionsChange}
          />
        }
      >
        <MapGraph
          data={mapShellView.displayMapData}
          mapLayersPending={mapShellView.showDeferredPending}
          homeworldMapLayerSucceeded={homeworldMapLayerSucceeded}
          displayMapFrameIsLive={mapShellView.displayMapFrameIsLive}
          className="h-full w-full min-h-0"
          analyticScope={analyticScope}
          roster={roster}
          futureTurnOffset={futureTurnOffset}
          onMapZoomChange={onMapZoomChange}
          onSetZoomReady={onSetZoomReady}
          planetLabelOptions={planetLabelOptions}
          cartography={cartography}
          fleetStreamPlayersById={fleetStreamPlayersById}
        />
      </MapPaneWithDisplayControls>
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-20 flex flex-col"
        data-testid="map-banner-stack"
      >
        <HomeworldBaselineDegradedBanner
          baselineDegraded={mapShellView.displayMapData.baselineDegraded === true}
          baselineTurn={mapShellView.displayMapData.baselineTurn}
        />
        <MapLayerErrorBanner error={mapShellView.layerError} />
        <DeferredPendingMessage pending={mapShellView.showDeferredPending} />
      </div>
    </main>
  )
}

/** Map-mode metadata note when homeworld baseline used a turn later than 1. */
function HomeworldBaselineDegradedBanner({
  baselineDegraded,
  baselineTurn,
}: {
  baselineDegraded: boolean
  baselineTurn: number | null | undefined
}) {
  if (!baselineDegraded) return null
  return (
    <p className="bg-black/90 px-4 py-1 text-xs text-amber-300/90" role="status">
      {homeworldBaselineDegradedMessage(baselineTurn)}
    </p>
  )
}

/** Partial map-analytic failure while other layers still render (e.g. homeworld gap). */
function MapLayerErrorBanner({ error }: { error: unknown }) {
  if (error == null) return null
  const detail = errorDetailFromUnknown(error)
  return (
    <p className="bg-black/90 px-4 py-1 text-xs text-red-300/90" role="alert">
      {detail}
    </p>
  )
}

/** Shows "Loading additional map data…" after a short delay. */
function DeferredPendingMessage({ pending }: { pending: boolean }) {
  const [show, setShow] = useState(false)
  useEffect(() => {
    let timeoutId: ReturnType<typeof setTimeout> | undefined

    if (pending) {
      timeoutId = setTimeout(() => setShow(true), 400)
    } else {
      setShow(false)
    }

    return () => {
      if (timeoutId !== undefined) {
        clearTimeout(timeoutId)
      }
    }
  }, [pending])
  if (!pending || !show) return null
  return (
    <p className="bg-black/90 px-4 py-1 text-sm text-gray-400">
      Loading additional map data…
    </p>
  )
}
