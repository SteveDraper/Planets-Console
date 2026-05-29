import type {
  MapDataResponse,
  MapEdge,
  MapNode,
  StellarCartographyOverlayCircle,
  WormholeUnknownEntrance,
} from '../../api/bff'
import {
  isCartographyLayerShown,
  type CartographyLayerVisibility,
  type StellarCartographySettingsGates,
} from './layers'
import type { WormholeDisplayMode } from './wormholeDisplayMode'

const STELLAR_CARTOGRAPHY_PREFIX = 'stellar-cartography'

export type AppendStellarCartographyMapLayerArgs = {
  data: MapDataResponse
  nodes: MapNode[]
  edges: MapEdge[]
  overlayCircles: StellarCartographyOverlayCircle[]
  wormholeUnknownEntrances: WormholeUnknownEntrance[]
  layerVisibility: CartographyLayerVisibility
  settingsGates: StellarCartographySettingsGates
  wormholeDisplayMode: WormholeDisplayMode
}

function filterOverlayCircles(
  circles: StellarCartographyOverlayCircle[],
  layerVisibility: CartographyLayerVisibility,
  settingsGates: StellarCartographySettingsGates,
  wormholeDisplayMode: WormholeDisplayMode
): StellarCartographyOverlayCircle[] {
  return circles.filter((circle) =>
    isCartographyLayerShown(circle.layer, {
      layerVisibility,
      settingsGates,
      wormholeDisplayMode,
    })
  )
}

function nodePositionById(nodes: MapDataResponse['nodes']): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>()
  for (const node of nodes) {
    positions.set(node.id, { x: Number(node.x), y: Number(node.y) })
  }
  return positions
}

/** Merge Stellar Cartography wormhole nodes/edges and filtered overlay circles into the combined map. */
export function appendStellarCartographyMapLayer({
  data,
  nodes,
  edges,
  overlayCircles,
  wormholeUnknownEntrances,
  layerVisibility,
  settingsGates,
  wormholeDisplayMode,
}: AppendStellarCartographyMapLayerArgs): void {
  const wormholesEnabled = isCartographyLayerShown('wormholes', {
    layerVisibility,
    settingsGates,
    wormholeDisplayMode,
  })
  const positions = nodePositionById(data.nodes)
  const connectedNodeIds = new Set<string>()

  if (wormholesEnabled) {
    for (const node of data.nodes) {
      nodes.push({
        id: `${STELLAR_CARTOGRAPHY_PREFIX}:${node.id}`,
        label: '',
        x: node.x,
        y: node.y,
      })
    }

    for (const rawEdge of data.edges) {
      connectedNodeIds.add(rawEdge.source)
      connectedNodeIds.add(rawEdge.target)
      const sourcePos = positions.get(rawEdge.source)
      const targetPos = positions.get(rawEdge.target)
      const edge: MapEdge = {
        source: `${STELLAR_CARTOGRAPHY_PREFIX}:${rawEdge.source}`,
        target: `${STELLAR_CARTOGRAPHY_PREFIX}:${rawEdge.target}`,
        layer: 'wormholes',
      }
      if (rawEdge.isBidirectional === true) edge.isBidirectional = true
      else if (rawEdge.isBidirectional === false) edge.isBidirectional = false
      if (rawEdge.stability != null) edge.stability = rawEdge.stability
      if (rawEdge.name != null) edge.name = rawEdge.name
      if (rawEdge.partnerId != null) edge.partnerId = rawEdge.partnerId
      if (sourcePos != null) {
        edge.sourceGameX = sourcePos.x
        edge.sourceGameY = sourcePos.y
      }
      if (targetPos != null) {
        edge.targetGameX = targetPos.x
        edge.targetGameY = targetPos.y
      }
      if (rawEdge.target.startsWith('wh-exit-')) {
        edge.wormholeExitOnly = true
      }
      edges.push(edge)
    }

    for (const node of data.nodes) {
      if (connectedNodeIds.has(node.id)) continue
      wormholeUnknownEntrances.push({ x: Number(node.x), y: Number(node.y) })
    }
  }

  const rawCircles = data.overlayCircles ?? []
  overlayCircles.push(
    ...filterOverlayCircles(rawCircles, layerVisibility, settingsGates, wormholeDisplayMode)
  )
}
