import type {
  CombinedMapData,
  MapEdge,
  StellarCartographyOverlayCircle,
  StellarCartographySampleEntry,
} from '../../api/bff'
import { isStellarCartographySampleLayerId } from '../../api/bff'
import {
  buildWormholeEndpointHoverIndex,
  type WormholeEndpointHoverInfo,
} from '../../lib/wormholeEndpointHover'
import type { CartographyLayerId } from './layers'
import {
  defaultCartographyLayerVisibility,
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
  isCartographyLayerShown,
} from './layers'
import {
  collectWormholeEndpoints,
  withoutCartographyNodes,
} from './cartographyWormholeFrame'
import type { StellarCartographyMapUiConfig } from './mapUiConfig'
import {
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
} from './clusterOutlineDisplayMode'
import {
  defaultWormholeDisplayMode,
  filterWormholeEdgesForDisplayMode,
} from './wormholeDisplayMode'

/** Static map frame fields derived from combined map data (before hover-sensitive edge filtering). */
export type CartographyMapFrameParts = {
  nodes: CombinedMapData['nodes']
  baseEdges: MapEdge[]
  wormholeUnknownEntrances: CombinedMapData['wormholeUnknownEntrances']
  wormholeEndpoints: { x: number; y: number }[]
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
}

/** Visibility and filtering rules shared by map rendering and hover sampling. */
export type CartographyVisibilityPolicy = {
  isLayerShown: (layerId: CartographyLayerId) => boolean
  overlayCircles: (
    circles: readonly StellarCartographyOverlayCircle[]
  ) => StellarCartographyOverlayCircle[]
  sampleEntries: (
    entries: readonly StellarCartographySampleEntry[]
  ) => StellarCartographySampleEntry[]
  areWormholesShown: () => boolean
  mapFrameParts: (data: CombinedMapData) => CartographyMapFrameParts
  mapEdges: (edges: readonly MapEdge[], wormholeLineRevealKey: string | null) => MapEdge[]
}

function hiddenWormholeFrameParts(data: CombinedMapData): CartographyMapFrameParts {
  const nodes = withoutCartographyNodes(data.nodes)
  return {
    nodes,
    baseEdges: data.edges.filter((edge) => edge.layer !== 'wormholes'),
    wormholeUnknownEntrances: [],
    wormholeEndpoints: [],
    wormholeEndpointHoverByCell: new Map(),
  }
}

export function cartographyVisibilityPolicy(
  config: StellarCartographyMapUiConfig
): CartographyVisibilityPolicy {
  const isLayerShown = (layerId: CartographyLayerId) =>
    isCartographyLayerShown(layerId, config)

  return {
    isLayerShown,
    overlayCircles: (circles) => circles.filter((circle) => isLayerShown(circle.layer)),
    sampleEntries: (entries) =>
      entries.filter(
        (entry): entry is StellarCartographySampleEntry =>
          isStellarCartographySampleLayerId(entry.layer) && isLayerShown(entry.layer)
      ),
    areWormholesShown: () => isLayerShown('wormholes'),
    mapFrameParts: (data) => {
      if (!isLayerShown('wormholes')) {
        return hiddenWormholeFrameParts(data)
      }
      const nodes = data.nodes
      return {
        nodes,
        baseEdges: [...data.edges],
        wormholeUnknownEntrances: data.wormholeUnknownEntrances,
        wormholeEndpoints: collectWormholeEndpoints(nodes, data.wormholeUnknownEntrances),
        wormholeEndpointHoverByCell: buildWormholeEndpointHoverIndex(
          data.edges,
          data.wormholeUnknownEntrances
        ),
      }
    },
    mapEdges: (edges, wormholeLineRevealKey) => {
      if (!isLayerShown('wormholes')) {
        return edges.filter((edge) => edge.layer !== 'wormholes')
      }
      return filterWormholeEdgesForDisplayMode(
        edges,
        config.wormholeDisplayMode,
        wormholeLineRevealKey
      )
    },
  }
}

/** Config with every layer gated off; its visibility policy hides all cartography artifacts. */
const ALL_LAYERS_HIDDEN_CONFIG: StellarCartographyMapUiConfig = {
  layerVisibility: defaultCartographyLayerVisibility(),
  settingsGates: EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
  wormholeDisplayMode: defaultWormholeDisplayMode(),
  starClusterDisplayMode: defaultStarClusterDisplayMode(),
  neutronClusterDisplayMode: defaultNeutronClusterDisplayMode(),
}

/** Used when Stellar Cartography is not enabled on the map. */
export const cartographyDisabledPolicy: CartographyVisibilityPolicy =
  cartographyVisibilityPolicy(ALL_LAYERS_HIDDEN_CONFIG)

export function cartographyFramePolicy(
  cartography: { policy: CartographyVisibilityPolicy } | undefined
): CartographyVisibilityPolicy {
  return cartography?.policy ?? cartographyDisabledPolicy
}
