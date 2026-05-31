import type {
  BlackHoleOverlayCircle,
  CartographyOverlayLayerId,
  DebrisDiskOverlayCircle,
  IonStormOverlayCircle,
  NebulaOverlayCircle,
  NeutronClusterOverlayCircle,
  StarClusterOverlayCircle,
  StellarCartographyOverlayCircle,
} from './bffCartographyTypes'
import { parseJsonFiniteNumber, parseJsonInteger } from './normalizeMapWireParsing'

type OverlayCircleBase = {
  id: string
  x: number
  y: number
  radius: number
}

function parseOverlayCircleBase(o: Record<string, unknown>): OverlayCircleBase | null {
  const id = typeof o.id === 'string' ? o.id : String(o.id ?? '')
  const x = parseJsonInteger(o.x)
  const y = parseJsonInteger(o.y)
  const radius = parseJsonFiniteNumber(o.radius)
  if (id === '' || x == null || y == null || radius == null || radius < 0) return null
  return { id, x, y, radius }
}

function normalizeDebrisDiskOverlay(
  o: Record<string, unknown>,
  base: OverlayCircleBase
): DebrisDiskOverlayCircle {
  const circle: DebrisDiskOverlayCircle = { ...base, layer: 'debris-disks' }
  if (typeof o.name === 'string') circle.name = o.name
  const planetId = parseJsonInteger(o.planetId ?? o.planet_id)
  if (planetId != null) circle.planetId = planetId
  return circle
}

function normalizeNebulaOverlay(
  o: Record<string, unknown>,
  base: OverlayCircleBase
): NebulaOverlayCircle {
  const circle: NebulaOverlayCircle = { ...base, layer: 'nebulae' }
  if (typeof o.name === 'string') circle.name = o.name
  const intensity = parseJsonFiniteNumber(o.intensity)
  if (intensity != null) circle.intensity = intensity
  const gas = parseJsonFiniteNumber(o.gas)
  if (gas != null) circle.gas = gas
  return circle
}

function normalizeIonStormOverlay(
  o: Record<string, unknown>,
  base: OverlayCircleBase
): IonStormOverlayCircle | null {
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

function normalizeClusterOverlay(
  o: Record<string, unknown>,
  base: OverlayCircleBase,
  layer: 'star-clusters' | 'neutron-clusters'
): StarClusterOverlayCircle | NeutronClusterOverlayCircle {
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

function normalizeBlackHoleOverlay(
  o: Record<string, unknown>,
  base: OverlayCircleBase
): BlackHoleOverlayCircle | null {
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

type OverlayCircleNormalizer = (
  o: Record<string, unknown>,
  base: OverlayCircleBase
) => StellarCartographyOverlayCircle | null

const overlayCircleNormalizers: Record<CartographyOverlayLayerId, OverlayCircleNormalizer> = {
  'debris-disks': (o, base) => normalizeDebrisDiskOverlay(o, base),
  nebulae: (o, base) => normalizeNebulaOverlay(o, base),
  'ion-storms': (o, base) => normalizeIonStormOverlay(o, base),
  'star-clusters': (o, base) => normalizeClusterOverlay(o, base, 'star-clusters'),
  'neutron-clusters': (o, base) => normalizeClusterOverlay(o, base, 'neutron-clusters'),
  'black-holes': (o, base) => normalizeBlackHoleOverlay(o, base),
}

export function normalizeOverlayCircle(raw: unknown): StellarCartographyOverlayCircle | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const layer = o.layer
  if (typeof layer !== 'string' || !(layer in overlayCircleNormalizers)) return null
  const base = parseOverlayCircleBase(o)
  if (base == null) return null
  return overlayCircleNormalizers[layer as CartographyOverlayLayerId](o, base)
}
