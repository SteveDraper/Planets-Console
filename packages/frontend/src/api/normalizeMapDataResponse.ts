/**
 * BFF map wire JSON normalization (syntactic parsing before UI merge).
 */

import type {
  BlackHoleOverlayCircle,
  DebrisDiskOverlayCircle,
  IllustrativeRouteStep,
  IonStormOverlayCircle,
  MapDataResponse,
  MapEdge,
  MapNode,
  MapPlanetSnapshot,
  NebulaOverlayCircle,
  NeutronClusterOverlayCircle,
  NormalWellMapCell,
  PlanetPairRoute,
  StarClusterOverlayCircle,
  StellarCartographyOverlayCircle,
} from "./bffCartographyTypes"

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

  if (layer === 'star-clusters' || layer === 'neutron-clusters') {
    const circle: StarClusterOverlayCircle | NeutronClusterOverlayCircle = {
      ...base,
      layer,
    }
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

function normalizeMapPlanetSnapshot(raw: unknown): MapPlanetSnapshot | undefined {
  if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  return { ...(raw as Record<string, unknown>) }
}

function normalizeMapNode(raw: unknown): MapNode | null {
  if (raw == null || typeof raw !== 'object') {
    return null
  }
  const n = raw as Record<string, unknown>
  const x = parseJsonFiniteNumber(n.x)
  const y = parseJsonFiniteNumber(n.y)
  if (x == null || y == null) {
    return null
  }
  const nested = n.planet ?? n.Planet
  const planet = normalizeMapPlanetSnapshot(nested)
  const base: MapNode = {
    id: typeof n.id === 'string' ? n.id : String(n.id ?? ''),
    label: typeof n.label === 'string' ? n.label : String(n.label ?? ''),
    x,
    y,
  }
  if (planet != null) {
    base.planet = planet
  }
  if (Object.prototype.hasOwnProperty.call(n, 'ownerName')) {
    const ownerRaw = n.ownerName
    if (ownerRaw === null) {
      base.ownerName = null
    } else if (typeof ownerRaw === 'string') {
      base.ownerName = ownerRaw
    }
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

function normalizeMapMeta(raw: unknown): MapDataResponse['meta'] | undefined {
  if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const meta = raw as Record<string, unknown>
  const out: NonNullable<MapDataResponse['meta']> = {}

  const nebulae = parseJsonInteger(meta.nebulae)
  if (nebulae != null) out.nebulae = nebulae

  const ionStorms = parseJsonInteger(meta.ionStorms ?? meta.ion_storms)
  if (ionStorms != null) out.ionStorms = ionStorms

  if (meta.nuIonStorms === true || meta.nuionstorms === true) {
    out.nuIonStorms = true
  }

  const starClusters = parseJsonInteger(meta.starClusters ?? meta.star_clusters)
  if (starClusters != null) out.starClusters = starClusters

  const neutronClusters = parseJsonInteger(meta.neutronClusters ?? meta.neutron_clusters)
  if (neutronClusters != null) out.neutronClusters = neutronClusters

  const blackHoles = parseJsonInteger(meta.blackHoles ?? meta.black_holes)
  if (blackHoles != null) out.blackHoles = blackHoles

  const wormholes = parseJsonInteger(meta.wormholes)
  if (wormholes != null) out.wormholes = wormholes

  const wormholeEdges = parseJsonInteger(meta.wormholeEdges ?? meta.wormhole_edges)
  if (wormholeEdges != null) out.wormholeEdges = wormholeEdges

  return Object.keys(out).length > 0 ? out : undefined
}

export function normalizeMapDataResponse(raw: unknown): MapDataResponse {
  if (raw == null || typeof raw !== 'object') {
    return { analyticId: '', nodes: [], edges: [] }
  }
  const o = raw as Record<string, unknown>
  const nodesRaw = o.nodes
  const edgesRaw = o.edges
  const routesRaw = o.routes
  const nodes = Array.isArray(nodesRaw)
    ? nodesRaw.map(normalizeMapNode).filter((node): node is MapNode => node != null)
    : []
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
  const metaRaw = o.meta
  const meta = normalizeMapMeta(metaRaw)
  if (meta != null) {
    out.meta = meta
  }
  return out
}
