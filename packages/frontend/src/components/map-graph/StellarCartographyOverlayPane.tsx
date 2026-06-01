import { useStore } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import type { StellarCartographyMapUiConfig } from '../../analytics/stellar-cartography/mapUiConfig'
import {
  buildStellarCartographyOverlayPaneShapes,
  hasVectorOverlayShapes,
} from '../../lib/cartography/stellarCartographyOverlay'
import { safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'
import { StellarCartographyVectorOverlay } from './StellarCartographyVectorOverlay'
import { WormholeEndpointMarkers } from './WormholeEndpointMarkers'
import type { WormholeEndpointHoverInfo } from '../../lib/wormholeEndpointHover'
import type { WormholeRecenterPulseTarget } from './stellarCartographyWormholeInteraction'

export function StellarCartographyOverlayPane({
  overlayCircles,
  wormholeEndpoints,
  cartographyConfig,
  wormholeEndpointHoverByCell,
  wormholeRecenterPulseTarget,
  blockedByPlanetHover,
  nuIonStorms,
}: {
  overlayCircles: CombinedMapData['overlayCircles']
  wormholeEndpoints: { x: number; y: number }[]
  cartographyConfig: StellarCartographyMapUiConfig
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
  wormholeRecenterPulseTarget: WormholeRecenterPulseTarget | null
  blockedByPlanetHover: boolean
  nuIonStorms?: boolean
}) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const { width, height } = useOverlayPaneSize(domNode)

  if (!transform || width <= 0 || height <= 0) return null
  if (overlayCircles.length === 0 && wormholeEndpoints.length === 0) return null

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const shapes = buildStellarCartographyOverlayPaneShapes(
    overlayCircles,
    wormholeEndpoints,
    { width, height, tx, ty, scale },
    {
      cloudyIonStorms: nuIonStorms ?? true,
      starClusterDisplayMode: cartographyConfig.starClusterDisplayMode,
      neutronClusterDisplayMode: cartographyConfig.neutronClusterDisplayMode,
    }
  )

  const hasVector = hasVectorOverlayShapes(shapes)
  const hasMarkers = shapes.wormholeMarkers.length > 0

  if (!hasVector && !hasMarkers) return null

  return (
    <div className="pointer-events-none absolute inset-0 z-[5]" aria-hidden>
      {hasVector ? (
        <StellarCartographyVectorOverlay shapes={shapes} width={width} height={height} />
      ) : null}
      <WormholeEndpointMarkers
        markers={shapes.wormholeMarkers}
        wormholeEndpointHoverByCell={wormholeEndpointHoverByCell}
        wormholeRecenterPulseTarget={wormholeRecenterPulseTarget}
        blockedByPlanetHover={blockedByPlanetHover}
      />
    </div>
  )
}
