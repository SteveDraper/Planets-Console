import { useStore } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import { buildStellarCartographyOverlayPaneShapes } from '../../lib/cartography/stellarCartographyOverlay'
import type { ClusterOutlineDisplayMode } from '../../analytics/stellar-cartography/clusterOutlineDisplayMode'
import { defaultNeutronClusterDisplayMode, defaultStarClusterDisplayMode } from '../../analytics/stellar-cartography/clusterOutlineDisplayMode'
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
  wormholeEndpointHoverByCell,
  wormholeRecenterPulseTarget,
  blockedByPlanetHover,
  nuIonStorms,
  starClusterDisplayMode = defaultStarClusterDisplayMode(),
  neutronClusterDisplayMode = defaultNeutronClusterDisplayMode(),
}: {
  overlayCircles: CombinedMapData['overlayCircles']
  wormholeEndpoints: { x: number; y: number }[]
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
  wormholeRecenterPulseTarget: WormholeRecenterPulseTarget | null
  blockedByPlanetHover: boolean
  nuIonStorms?: boolean
  starClusterDisplayMode?: ClusterOutlineDisplayMode
  neutronClusterDisplayMode?: ClusterOutlineDisplayMode
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
      starClusterDisplayMode,
      neutronClusterDisplayMode,
    }
  )

  const hasVector =
    shapes.circles.length > 0 ||
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
