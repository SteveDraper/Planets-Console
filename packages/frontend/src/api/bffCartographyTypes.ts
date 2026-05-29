/**
 * Stellar Cartography and shared map wire types for the BFF client.
 * Normalization helpers live here alongside the types they produce.
 */

import type { components } from './schema'

/** Game map cell coordinates from OpenAPI `MapCellModel`. */
export type MapCell = components['schemas']['MapCellModel']

/** Map cell whose center lies in a planet's normal warp well (from base-map). */
export type NormalWellMapCell = MapCell

/** Node position in the map's fixed Cartesian coordinate system. */
export type MapNode = {
  id: string
  label: string
  x: number
  y: number
  /** Present for base-map planets; full turn snapshot fields for map labels. */
  planet?: Record<string, unknown>
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
  | BlackHoleOverlayCircle

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
    starClusters?: number
    blackHoles?: number
    wormholes?: number
    wormholeEdges?: number
  }
}

/** Parse a single JSON number; rejects null, non-numeric, and `Number('')` → 0. */
function parseJsonFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null
  }
  if (typeof value === 'string') {
    if (value.trim() === '') return null
    const n = Number(value)
    return Number.isFinite(n) ? n : null
  }
  return null
}

/** Parse a map grid cell index; must be a finite integer (no boolean/null/`""` coercion). */
function parseJsonInteger(value: unknown): number | null {
  const n = parseJsonFiniteNumber(value)
  if (n == null || !Number.isInteger(n)) return null
  return n
}

/**
 * 2D offset tuple from the wire. Each element must be a finite `number` or a non-empty
 * numeric string — never `Number()` on arbitrary values (avoids `null`/`""` → `0`).
 */
function parseFiniteNumberPair(
  s: Record<string, unknown>,
  camelKey: string,
  snakeKey: string
): [number, number] | undefined {
  const raw = s[camelKey] ?? s[snakeKey]
  if (raw == null) return undefined
  if (!Array.isArray(raw) || raw.length !== 2) return undefined
  const a = parseJsonFiniteNumber(raw[0])
  const b = parseJsonFiniteNumber(raw[1])
  if (a == null || b == null) return undefined
  return [a, b]
}

function normalizeIllustrativeRouteStep(raw: unknown): IllustrativeRouteStep | null {
  if (raw == null || typeof raw !== 'object') return null
  const s = raw as Record<string, unknown>
  const kind = s.kind === 'flare' ? 'flare' : s.kind === 'normal' ? 'normal' : null
  if (kind == null) return null
  const toRaw = s.to
  if (toRaw == null || typeof toRaw !== 'object') return null
  const t = toRaw as Record<string, unknown>
  const x = parseJsonFiniteNumber(t.x)
  const y = parseJsonFiniteNumber(t.y)
  if (x == null || y == null) return null
  const out: IllustrativeRouteStep = { kind, to: { x, y } }
  const wp = parseFiniteNumberPair(s, 'waypointOffset', 'waypoint_offset')
  if (wp != null) {
    out.waypointOffset = wp
  }
  const ar = parseFiniteNumberPair(s, 'arrivalOffset', 'arrival_offset')
  if (ar != null) {
    out.arrivalOffset = ar
  }
  return out
}

/**
 * Parses each node so `planet` / `ownerName` are plain objects (not lost to reference sharing).
 * Accepts `Planet` as an alternate key for the nested snapshot (defensive).
 */
function normalizePlanetPairRoute(raw: unknown): PlanetPairRoute | null {
  if (raw == null || typeof raw !== 'object') return null
  const r = raw as Record<string, unknown>
  const fromRaw = r.fromPlanetId ?? r.from_planet_id
  const toRaw = r.toPlanetId ?? r.to_planet_id
  const fromPlanetId = typeof fromRaw === 'number' ? fromRaw : Number(fromRaw)
  const toPlanetId = typeof toRaw === 'number' ? toRaw : Number(toRaw)
  if (!Number.isFinite(fromPlanetId) || !Number.isFinite(toPlanetId)) return null
  let illustrativeRoute: IllustrativeRouteStep[] | undefined
  const irRaw = r.illustrativeRoute ?? r.illustrative_route
  if (Array.isArray(irRaw) && irRaw.length > 0) {
    const steps = irRaw
      .map(normalizeIllustrativeRouteStep)
      .filter((s): s is IllustrativeRouteStep => s != null)
    if (steps.length > 0) illustrativeRoute = steps
  }
  const o: PlanetPairRoute = {
    fromPlanetId,
    toPlanetId,
    viaFlare: r.viaFlare === true,
  }
  if (illustrativeRoute != null) {
    o.illustrativeRoute = illustrativeRoute
  }
  return o
}

function normalizeMapEdge(raw: unknown): MapEdge | null {
  if (raw == null || typeof raw !== 'object') return null
  const e = raw as Record<string, unknown>
  const source = typeof e.source === 'string' ? e.source : String(e.source ?? '')
  const target = typeof e.target === 'string' ? e.target : String(e.target ?? '')
  if (source === '' || target === '') return null
  const edge: MapEdge = { source, target }
  if (e.viaFlare === true) edge.viaFlare = true
  if (e.layer === 'wormholes') edge.layer = 'wormholes'
  if (e.isBidirectional === true) edge.isBidirectional = true
  else if (e.isBidirectional === false) edge.isBidirectional = false
  const stability = parseJsonFiniteNumber(e.stability)
  if (stability != null) edge.stability = stability
  if (typeof e.name === 'string') edge.name = e.name
  const partnerId = parseJsonInteger(e.partnerId ?? e.partner_id)
  if (partnerId != null) edge.partnerId = partnerId
  return edge
}

function normalizeOverlayCircle(raw: unknown): StellarCartographyOverlayCircle | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const layer = o.layer
  const id = typeof o.id === 'string' ? o.id : String(o.id ?? '')
  const x = parseJsonInteger(o.x)
  const y = parseJsonInteger(o.y)
  const radius = parseJsonFiniteNumber(o.radius)
  if (id === '' || x == null || y == null || radius == null || radius < 0) return null

  const base = { id, x, y, radius }

  if (layer === 'debris-disks') {
    const circle: DebrisDiskOverlayCircle = { ...base, layer: 'debris-disks' }
    if (typeof o.name === 'string') circle.name = o.name
    const planetId = parseJsonInteger(o.planetId ?? o.planet_id)
    if (planetId != null) circle.planetId = planetId
    return circle
  }

  if (layer === 'nebulae') {
    const circle: NebulaOverlayCircle = { ...base, layer: 'nebulae' }
    if (typeof o.name === 'string') circle.name = o.name
    const intensity = parseJsonFiniteNumber(o.intensity)
    if (intensity != null) circle.intensity = intensity
    const gas = parseJsonFiniteNumber(o.gas)
    if (gas != null) circle.gas = gas
    return circle
  }

  if (layer === 'ion-storms') {
    const voltage = parseJsonInteger(o.voltage)
    const stormClass = parseJsonInteger(o.class)
    if (voltage == null || stormClass == null) return null
    const circle: IonStormOverlayCircle = {
      ...base,
      layer: 'ion-storms',
      voltage,
      class: stormClass,
    }
    const heading = parseJsonFiniteNumber(o.heading)
    if (heading != null) circle.heading = heading
    const warp = parseJsonInteger(o.warp)
    if (warp != null) circle.warp = warp
    const parentId = parseJsonInteger(o.parentId ?? o.parentid)
    if (parentId != null) circle.parentId = parentId
    if (o.isGrowing === true || o.isgrowing === true) circle.isGrowing = true
    return circle
  }

  if (layer === 'star-clusters') {
    const circle: StarClusterOverlayCircle = { ...base, layer: 'star-clusters' }
    if (typeof o.name === 'string') circle.name = o.name
    const temp = parseJsonFiniteNumber(o.temp)
    if (temp != null) circle.temp = temp
    const mass = parseJsonFiniteNumber(o.mass)
    if (mass != null) circle.mass = mass
    const planets = parseJsonInteger(o.planets)
    if (planets != null) circle.planets = planets
    return circle
  }

  if (layer === 'black-holes') {
    const coreRadius = parseJsonFiniteNumber(o.coreRadius ?? o.coreradius)
    const bandRadius = parseJsonFiniteNumber(o.bandRadius ?? o.bandradius)
    if (coreRadius == null || bandRadius == null) return null
    const circle: BlackHoleOverlayCircle = {
      ...base,
      layer: 'black-holes',
      coreRadius,
      bandRadius,
    }
    if (typeof o.name === 'string') circle.name = o.name
    return circle
  }

  return null
}

function normalizeMapNode(raw: unknown): MapNode {
  if (raw == null || typeof raw !== 'object') {
    return { id: '', label: '', x: 0, y: 0 }
  }
  const n = raw as Record<string, unknown>
  const nested = n.planet ?? n.Planet
  const planet =
    nested != null && typeof nested === 'object' && !Array.isArray(nested)
      ? ({ ...(nested as Record<string, unknown>) } as Record<string, unknown>)
      : undefined
  const base: MapNode = {
    id: typeof n.id === 'string' ? n.id : String(n.id ?? ''),
    label: typeof n.label === 'string' ? n.label : String(n.label ?? ''),
    x: typeof n.x === 'number' ? n.x : Number(n.x) || 0,
    y: typeof n.y === 'number' ? n.y : Number(n.y) || 0,
  }
  if (planet != null) {
    base.planet = planet
  }
  if (Object.prototype.hasOwnProperty.call(n, 'ownerName')) {
    base.ownerName = n.ownerName as string | null | undefined
  }
  const rawCells = n.normalWellCells ?? n.normal_well_cells
  if (Array.isArray(rawCells)) {
    base.normalWellCells = rawCells
      .map((cell) => {
        if (cell == null || typeof cell !== 'object') return null
        const c = cell as Record<string, unknown>
        const x = parseJsonInteger(c.x)
        const y = parseJsonInteger(c.y)
        if (x == null || y == null) return null
        return { x, y }
      })
      .filter((cell): cell is NormalWellMapCell => cell != null)
  }
  return base
}

export function normalizeMapDataResponse(raw: unknown): MapDataResponse {
  if (raw == null || typeof raw !== 'object') {
    return { analyticId: '', nodes: [], edges: [] }
  }
  const o = raw as Record<string, unknown>
  const nodesRaw = o.nodes
  const edgesRaw = o.edges
  const routesRaw = o.routes
  const nodes = Array.isArray(nodesRaw) ? nodesRaw.map(normalizeMapNode) : []
  const edges = Array.isArray(edgesRaw)
    ? (edgesRaw.map(normalizeMapEdge).filter((e) => e != null) as MapEdge[])
    : []
  const routes = Array.isArray(routesRaw)
    ? (routesRaw.map(normalizePlanetPairRoute).filter((r) => r != null) as PlanetPairRoute[])
    : undefined
  const out: MapDataResponse = {
    analyticId: typeof o.analyticId === 'string' ? o.analyticId : String(o.analyticId ?? ''),
    nodes,
    edges,
  }
  if (routes != null) {
    out.routes = routes
  }
  const overlayCircles = o.overlayCircles
  if (Array.isArray(overlayCircles)) {
    out.overlayCircles = overlayCircles
      .map(normalizeOverlayCircle)
      .filter((c): c is StellarCartographyOverlayCircle => c != null)
  }
  const meta = o.meta
  if (meta != null && typeof meta === 'object' && !Array.isArray(meta)) {
    out.meta = meta as MapDataResponse['meta']
  }
  return out
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
