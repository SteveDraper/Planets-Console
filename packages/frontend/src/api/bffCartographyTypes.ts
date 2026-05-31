/**
 * Stellar Cartography and shared map wire types for the BFF client.
 * Wire JSON normalization lives in `normalizeMapDataResponse.ts`.
 */

import type { components } from './schema'

/** Game map cell coordinates from OpenAPI `MapCellModel`. */
export type MapCell = components['schemas']['MapCellModel']

/** Map cell whose center lies in a planet's normal warp well (from base-map). */
export type NormalWellMapCell = MapCell

/**
 * Turn planet snapshot embedded on map wire nodes (Planets.nu host field names).
 * Additional host keys are allowed for debug labels and forward compatibility.
 */
export type MapPlanetSnapshot = {
  id?: number | string
  name?: string
  ownerid?: number
  temp?: number
  neutronium?: number
  nativetype?: number
  nativeracename?: string
  nativeclans?: number
  clans?: number
  duranium?: number
  groundduranium?: number
  densityduranium?: number
  tritanium?: number
  groundtritanium?: number
  densitytritanium?: number
  molybdenum?: number
  groundmolybdenum?: number
  densitymolybdenum?: number
  groundneutronium?: number
  densityneutronium?: number
  [key: string]: unknown
}

/** Node position in the map's fixed Cartesian coordinate system. */
export type MapNode = {
  id: string
  label: string
  x: number
  y: number
  /** Present for base-map planets; full turn snapshot fields for map labels. */
  planet?: MapPlanetSnapshot
  /** Resolved from turn players when `planet` is present. */
  ownerName?: string | null
  /** Normal warp well cells from base-map; empty for debris-disk planets. */
  normalWellCells?: NormalWellMapCell[]
}

/** Edge in map wire format or after combining route pairs onto base-map node ids. */
export type MapEdge = {
  source: string
  target: string
  /** True when reachability uses a flare (dashed edge on the map). */
  viaFlare?: boolean
  /**
   * Intermediate map cells (game integer coordinates) between source and target.
   * When set, the map draws a polyline A → waypoints → B instead of a single segment.
   */
  waypointsInGame?: MapCell[]
  /** Stellar Cartography wormhole edge metadata. */
  layer?: 'wormholes'
  isBidirectional?: boolean
  stability?: number
  name?: string
  partnerId?: number
  /** Game map cell coords at source/target endpoints (for wormhole hover and recenter). */
  sourceGameX?: number
  sourceGameY?: number
  targetGameX?: number
  targetGameY?: number
  /** True when the source node is a mono-directional exit (not the entrance). */
  wormholeExitOnly?: boolean
}

export type CartographyOverlayLayerId =
  | 'debris-disks'
  | 'nebulae'
  | 'ion-storms'
  | 'star-clusters'
  | 'neutron-clusters'
  | 'black-holes'

type CartographyOverlayCircleBase = {
  layer: CartographyOverlayLayerId
  id: string
  x: number
  y: number
  radius: number
}

export type DebrisDiskOverlayCircle = CartographyOverlayCircleBase & {
  layer: 'debris-disks'
  name?: string
  planetId?: number
}

export type NebulaOverlayCircle = CartographyOverlayCircleBase & {
  layer: 'nebulae'
  name?: string
  intensity?: number
  gas?: number
}

export type IonStormOverlayCircle = CartographyOverlayCircleBase & {
  layer: 'ion-storms'
  voltage?: number
  class: number
  heading?: number
  warp?: number
  parentId?: number
  isGrowing?: boolean
}

export type StarClusterOverlayCircle = CartographyOverlayCircleBase & {
  layer: 'star-clusters'
  name?: string
  temp?: number
  mass?: number
  planets?: number
}

export type NeutronClusterOverlayCircle = CartographyOverlayCircleBase & {
  layer: 'neutron-clusters'
  name?: string
  temp?: number
  mass?: number
  planets?: number
}

export type BlackHoleOverlayCircle = CartographyOverlayCircleBase & {
  layer: 'black-holes'
  name?: string
  coreRadius: number
  bandRadius: number
}

export type StellarCartographyOverlayCircle =
  | DebrisDiskOverlayCircle
  | NebulaOverlayCircle
  | IonStormOverlayCircle
  | StarClusterOverlayCircle
  | NeutronClusterOverlayCircle
  | BlackHoleOverlayCircle

export function isDebrisDiskOverlayCircle(
  circle: StellarCartographyOverlayCircle
): circle is DebrisDiskOverlayCircle {
  return circle.layer === 'debris-disks'
}

export function isNebulaOverlayCircle(
  circle: StellarCartographyOverlayCircle
): circle is NebulaOverlayCircle {
  return circle.layer === 'nebulae'
}

export function isIonStormOverlayCircle(
  circle: StellarCartographyOverlayCircle
): circle is IonStormOverlayCircle {
  return circle.layer === 'ion-storms'
}

export function isStarClusterOverlayCircle(
  circle: StellarCartographyOverlayCircle
): circle is StarClusterOverlayCircle {
  return circle.layer === 'star-clusters'
}

export function isNeutronClusterOverlayCircle(
  circle: StellarCartographyOverlayCircle
): circle is NeutronClusterOverlayCircle {
  return circle.layer === 'neutron-clusters'
}

export function isBlackHoleOverlayCircle(
  circle: StellarCartographyOverlayCircle
): circle is BlackHoleOverlayCircle {
  return circle.layer === 'black-holes'
}

/** Unknown-target wormhole entrance rendered as a sky dot in the SVG overlay. */
export type WormholeUnknownEntrance = MapCell

/** One hop in a Core `illustrativeRoute` (normal move or flare). */
export type IllustrativeRouteStep = {
  kind: 'normal' | 'flare'
  to: MapCell
  waypointOffset?: [number, number]
  arrivalOffset?: [number, number]
}

/** UI-independent planet pair from the Connections analytic (Core/BFF). */
export type PlanetPairRoute = {
  fromPlanetId: number
  toPlanetId: number
  viaFlare: boolean
  /** Present when the server was asked for illustrative paths (multi-hop flares). */
  illustrativeRoute?: IllustrativeRouteStep[]
}

export type MapDataResponse = {
  analyticId: string
  nodes: MapNode[]
  edges: MapEdge[]
  routes?: PlanetPairRoute[]
  overlayCircles?: StellarCartographyOverlayCircle[]
  meta?: {
    nebulae?: number
    ionStorms?: number
    /** When true, ion storm voltage falls off inside each sub-circle (Stellar Cartography). */
    nuIonStorms?: boolean
    /** Distinct cluster names (not star body count). */
    starClusters?: number
    /** Distinct neutron cluster names (not star body count). */
    neutronClusters?: number
    blackHoles?: number
    wormholes?: number
    wormholeEdges?: number
  }
}
/** Intermediate cell along a multi-hop flare (game map integer coordinates), for subtle markers. */
export type RouteMapWaypoint = {
  id: string
  gx: number
  gy: number
}

/** Combined nodes/edges from multiple analytics for the single shared map. */
export type CombinedMapData = {
  nodes: MapDataResponse['nodes']
  edges: MapEdge[]
  /** Deduped intermediate cells for illustrated flare routes (when `includeIllustrativeRoutes` was requested). */
  routeWaypoints: RouteMapWaypoint[]
  /** Filtered Stellar Cartography disc overlays (layer toggles + settings gates applied). */
  overlayCircles: StellarCartographyOverlayCircle[]
  /** Wormhole entrances with unknown targets (6px sky dots). */
  wormholeUnknownEntrances: WormholeUnknownEntrance[]
  /** Stellar Cartography ion storm mode from turn settings (`nuionstorms`). */
  nuIonStorms?: boolean
}

/** Wire `layer` values returned by Core sample-at (overlay layers plus wormholes). */
export type StellarCartographySampleLayerId = CartographyOverlayLayerId | 'wormholes'

const STELLAR_CARTOGRAPHY_SAMPLE_LAYER_IDS: readonly StellarCartographySampleLayerId[] = [
  'debris-disks',
  'nebulae',
  'ion-storms',
  'star-clusters',
  'neutron-clusters',
  'black-holes',
  'wormholes',
] as const

export function isStellarCartographySampleLayerId(
  layer: string
): layer is StellarCartographySampleLayerId {
  return (STELLAR_CARTOGRAPHY_SAMPLE_LAYER_IDS as readonly string[]).includes(layer)
}

export type StellarCartographySampleEntry =
  | { layer: 'debris-disks'; lines: string[] }
  | { layer: 'nebulae'; lines: string[] }
  | { layer: 'ion-storms'; lines: string[] }
  | { layer: 'star-clusters'; lines: string[] }
  | { layer: 'neutron-clusters'; lines: string[] }
  | { layer: 'black-holes'; lines: string[] }
  | { layer: 'wormholes'; lines: string[] }

export type StellarCartographySampleResponse = {
  x: number
  y: number
  entries: StellarCartographySampleEntry[]
}

export type StellarCartographyTurnSummaryResponse = {
  ionStormCount: number
  nuIonStorms: boolean
}
