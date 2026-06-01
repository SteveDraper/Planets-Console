import { useEffect, useState } from 'react'
import type { StellarCartographyMapContext } from '../../analytics/stellar-cartography/mapUiConfig'
import { MapGraph } from '../MapGraph'
import { MapPaneWithDisplayControls } from '../MapPaneWithDisplayControls'
import { PlanetMapInfoControls } from '../PlanetMapInfoControls'
import type { PlanetLabelOptions } from '../planetMapLabelModel'
import { ShellCenterPane, ShellErrorPane } from './ShellPlaceholders'
import type { MapShellView } from '../../lib/mapDisplayRetention'

type MapShellContentProps = {
  mapShellView: MapShellView
  planetLabelOptions: PlanetLabelOptions
  onPlanetLabelOptionsChange: (value: PlanetLabelOptions) => void
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  cartography?: StellarCartographyMapContext
}

/** Renders map shell phases (loading, error, or live map with optional deferred pending banner). */
export function MapShellContent({
  mapShellView,
  planetLabelOptions,
  onPlanetLabelOptionsChange,
  onMapZoomChange,
  onSetZoomReady,
  cartography,
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
          planetLabelOptions={planetLabelOptions}
          onPlanetLabelOptionsChange={onPlanetLabelOptionsChange}
          onMapZoomChange={onMapZoomChange}
          onSetZoomReady={onSetZoomReady}
          cartography={cartography}
        />
      )
  }
}

function MapShellShowingMap({
  mapShellView,
  planetLabelOptions,
  onPlanetLabelOptionsChange,
  onMapZoomChange,
  onSetZoomReady,
  cartography,
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
          className="h-full w-full min-h-0"
          onMapZoomChange={onMapZoomChange}
          onSetZoomReady={onSetZoomReady}
          planetLabelOptions={planetLabelOptions}
          cartography={cartography}
        />
      </MapPaneWithDisplayControls>
      <DeferredPendingMessage pending={mapShellView.showDeferredPending} />
    </main>
  )
}

/** Shows "Loading additional map data…" after a short delay. Overlays the map so the pane size never changes. */
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
    <p className="pointer-events-none absolute inset-x-0 top-0 z-20 bg-black/90 px-4 py-1 text-sm text-gray-400">
      Loading additional map data…
    </p>
  )
}
