import { useMemo } from 'react'
import { useStore } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import type { StellarCartographyMapUiConfig } from '../../analytics/mapLayers'
import {
  areCartographyWormholesShown,
  filterCartographyOverlayCircles,
} from '../../analytics/stellar-cartography/overlayDisplayFilter'
import { buildStellarCartographyOverlayPaneShapes } from '../../lib/cartography/stellarCartographyOverlay'
import { safeZoomScale } from './geometry'
import { useOverlayPaneSize } from './useOverlayPaneSize'
import { StellarCartographyVectorOverlay } from './StellarCartographyVectorOverlay'
import { WormholeEndpointMarkers } from './WormholeEndpointMarkers'
import type { WormholeEndpointHoverInfo } from '../../lib/wormholeEndpointHover'
import type { WormholeRecenterPulseTarget } from './stellarCartographyWormholeInteraction'

const STELLAR_CARTOGRAPHY_NODE_PREFIX = 'stellar-cartography:'

export function collectWormholeEndpoints(
  nodes: CombinedMapData['nodes'],
  unknownEntrances: CombinedMapData['wormholeUnknownEntrances']
): { x: number; y: number }[] {
  const seen = new Set<string>()
  const endpoints: { x: number; y: number }[] = []
  const add = (x: number, y: number) => {
    const key = `${x},${y}`
    if (seen.has(key)) return
    seen.add(key)
    endpoints.push({ x, y })
  }
  for (const node of nodes) {
    if (node.id.startsWith(STELLAR_CARTOGRAPHY_NODE_PREFIX)) {
      add(Number(node.x), Number(node.y))
    }
  }
  for (const entrance of unknownEntrances) {
    add(entrance.x, entrance.y)
  }
  return endpoints
}

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

  const visibleOverlayCircles = useMemo(
    () => filterCartographyOverlayCircles(overlayCircles, cartographyConfig),
    [overlayCircles, cartographyConfig]
  )
  const visibleWormholeEndpoints = useMemo(
    () => (areCartographyWormholesShown(cartographyConfig) ? wormholeEndpoints : []),
    [cartographyConfig, wormholeEndpoints]
  )

  if (!transform || width <= 0 || height <= 0) return null
  if (visibleOverlayCircles.length === 0 && visibleWormholeEndpoints.length === 0) return null

  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const shapes = buildStellarCartographyOverlayPaneShapes(
    visibleOverlayCircles,
    visibleWormholeEndpoints,
    { width, height, tx, ty, scale },
    {
      cloudyIonStorms: nuIonStorms ?? true,
      starClusterDisplayMode: cartographyConfig.starClusterDisplayMode,
      neutronClusterDisplayMode: cartographyConfig.neutronClusterDisplayMode,
    }
  )

  const hasVector =
    shapes.circles.length > 0 ||
    shapes.blackHoles.length > 0 ||
    shapes.annuli.length > 0 ||
    shapes.nebulaClouds.length > 0 ||
    shapes.ionStormClouds.length > 0 ||
    shapes.neutronFluxClouds.length > 0 ||
    shapes.debrisDiskBorders.length > 0 ||
    shapes.arrows.length > 0
  const hasMarkers = shapes.wormholeMarkers.length > 0

  if (!hasVector && !hasMarkers) return null

  return (
    <div className="pointer-events-none absolute inset-0 z-[5]" aria-hidden>
      {hasVector ? (
        <StellarCartographyVectorOverlay
          shapes={{
            nebulaClouds: shapes.nebulaClouds,
            ionStormClouds: shapes.ionStormClouds,
            neutronFluxClouds: shapes.neutronFluxClouds,
            circles: shapes.circles,
            blackHoles: shapes.blackHoles,
            annuli: shapes.annuli,
            debrisDiskBorders: shapes.debrisDiskBorders,
            arrows: shapes.arrows,
          }}
          width={width}
          height={height}
        />
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
