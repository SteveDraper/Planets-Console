/** Class boundary voltages (meV): iso-contours between hazard tiers. */
export const ION_STORM_CLASS_VOLTAGE_THRESHOLDS = [50, 100, 150, 200] as const

/** Outer storm edge: summed voltage above this counts as inside the field. */
export const ION_STORM_OUTER_VOLTAGE_THRESHOLD = 0.5

export const ION_STORM_BOUNDARY_STROKE_WIDTH = 0.75
export const ION_STORM_MAX_RASTER_PX = 512
export const ION_STORM_BOUNDARY_MAX_GRID_CELLS = 512
export const ION_STORM_BOUNDARY_RAY_COUNT = 512

export const NEBULA_CLOUD_COLOR = '#7d8f7b'
export const NEBULA_STROKE_COLOR = '#8fa08d'
export const NEBULA_CLOUD_COLOR_RGB: readonly [number, number, number] = [125, 143, 123]

/** Host visibility formula (tooltip). */
export const NEBULA_VISIBILITY_NUMERATOR = 4000
export const NEBULA_VISIBILITY_MAX_LY = 250
/** Dense end of the in-nebula range (~density 88). */
export const NEBULA_DENSE_VISIBILITY_LY = 45
/** Sparse end for fill opacity gradient (fade to black; tooltip can read higher ly). */
export const NEBULA_FILL_SPARSE_VISIBILITY_LY = 200
export const NEBULA_SPARSE_VISIBILITY_LY = NEBULA_FILL_SPARSE_VISIBILITY_LY

export const NEBULA_MAX_FILL_OPACITY = 0.55
export const NEBULA_MIN_FILL_OPACITY = 0.06
export const NEBULA_CLOUD_NOISE_STRENGTH = 0.22
export const NEBULA_MAP_SAMPLE_STEP_LY = 1
export const NEBULA_BOUNDARY_DENSITY_THRESHOLD = 0.2
export const NEBULA_STROKE_WIDTH = 0.5

/** Debris disk border outline (planetoids stay on the base map). */
export const DEBRIS_DISK_BORDER_STROKE = '#dc2626'
export const DEBRIS_DISK_BORDER_STROKE_WIDTH = 1

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

/** Map visibility (ly) to cloud fill opacity: lower visibility = denser fog = more cloud. */
export function nebulaFillOpacityFromVisibility(visibilityLy: number): number {
  const span = NEBULA_FILL_SPARSE_VISIBILITY_LY - NEBULA_DENSE_VISIBILITY_LY
  if (span <= 0) return NEBULA_MAX_FILL_OPACITY
  const sparseFraction = clamp01((visibilityLy - NEBULA_DENSE_VISIBILITY_LY) / span)
  return (
    NEBULA_MAX_FILL_OPACITY * (1 - sparseFraction) +
    NEBULA_MIN_FILL_OPACITY * sparseFraction
  )
}

/** Host-aligned visibility from summed nebula density (matches Core sample_at). */
export function nebulaVisibilityLyFromDensity(density: number): number {
  if (density <= 0) return NEBULA_VISIBILITY_MAX_LY
  return Math.min(
    NEBULA_VISIBILITY_MAX_LY,
    Math.round(NEBULA_VISIBILITY_NUMERATOR / (density + 1))
  )
}

/** Fill opacity from host density via the same visibility math as hover tooltips. */
export function nebulaFillOpacityFromHostDensity(hostDensity: number): number {
  if (hostDensity <= 0) return 0
  return nebulaFillOpacityFromVisibility(nebulaVisibilityLyFromDensity(hostDensity))
}

/** Cool star body color (low temp). */
export const STAR_CLUSTER_COOL_COLOR = '#dc2626'
/** Hot star body color (high temp). */
export const STAR_CLUSTER_HOT_COLOR = '#f8fafc'

/** Neutron cluster lethal core and flux palette (game client blue). */
export const NEUTRON_CLUSTER_CORE_COLOR = '#7dd3fc'
export const NEUTRON_CLUSTER_CORE_HOT_COLOR = '#e0f2fe'
export const NEUTRON_CLUSTER_FLUX_RGB: readonly [number, number, number] = [56, 189, 248]
export const NEUTRON_CLUSTER_FLUX_MAX_RASTER_PX = 512
export const NEUTRON_CLUSTER_BOUNDARY_MAX_GRID_CELLS = 512

const NEUTRON_CLUSTER_CORE_RGB: readonly [number, number, number] = [125, 211, 252]
const NEUTRON_CLUSTER_CORE_HOT_RGB: readonly [number, number, number] = [224, 242, 254]

/** Log-scale temperature anchors for red (low) to white (high) fill color. */
export const STAR_CLUSTER_TEMP_COLOR_MIN = 10_000
export const STAR_CLUSTER_TEMP_COLOR_MAX = 50_000

const STAR_CLUSTER_COOL_RGB: readonly [number, number, number] = [220, 38, 38]
const STAR_CLUSTER_HOT_RGB: readonly [number, number, number] = [248, 250, 252]

export const BLACK_HOLE_CORE_FILL = '#0f0f12'
export const BLACK_HOLE_BAND_FILL = '#7c3aed'
export const BLACK_HOLE_BAND_STROKE = '#7c3aed'

export const WORMHOLE_LINE_STROKE = '#38bdf8'
export const WORMHOLE_SPIRAL_BLUE = '#5c6670'
export const WORMHOLE_SPIRAL_ORANGE = '#646058'
export const WORMHOLE_ENDPOINT_DISC_FILL = '#1c1c1e'
/** Wormhole endpoint marker diameter in map light-years (scales with zoom). */
export const WORMHOLE_ENDPOINT_DIAMETER_LY = 5
/** Header slider shows zoom as percent (300% = 3); icons never shrink below map size at this zoom. */
export const WORMHOLE_ENDPOINT_MIN_RENDER_ZOOM = 3
export const WORMHOLE_ENDPOINT_MIN_DIAMETER_PX =
  WORMHOLE_ENDPOINT_DIAMETER_LY * WORMHOLE_ENDPOINT_MIN_RENDER_ZOOM
/** Duration of the post-recenter pulse animation on the target wormhole icon. */
export const WORMHOLE_RECENTER_PULSE_MS = 3000

const ION_STORM_FILL_OPACITY: Record<number, number> = {
  1: 0.15,
  2: 0.3,
  3: 0.45,
  4: 0.6,
  5: 0.75,
}

const ION_STORM_STROKE: Record<number, string> = {
  1: '#eab308',
  2: '#eab308',
  3: '#eab308',
  4: '#f97316',
  5: '#ef4444',
}

const ION_STORM_RIM_OPACITY: Record<number, number> = {
  1: 0.6,
  2: 0.6,
  3: 0.6,
  4: 0.8,
  5: 0.8,
}

export function ionStormFillOpacity(stormClass: number): number {
  return ION_STORM_FILL_OPACITY[stormClass] ?? ION_STORM_FILL_OPACITY[1]
}

export function ionStormStrokeColor(stormClass: number): string {
  return ION_STORM_STROKE[stormClass] ?? ION_STORM_STROKE[1]
}

export function ionStormRimOpacity(stormClass: number): number {
  return ION_STORM_RIM_OPACITY[stormClass] ?? ION_STORM_RIM_OPACITY[1]
}

/** Disc fill alpha for nebulae and star clusters. */
export const DISC_FILL_ALPHA = 0.2
export const DISC_RIM_ALPHA = 0.6

/** Lethal core hotspot at center (small, bright, temp-colored). */
export const STAR_CLUSTER_CORE_HOTSPOT_RADIUS_FRACTION = 0.12
export const STAR_CLUSTER_CORE_HOTSPOT_OPACITY = 0.88

/** Lethal core fill opacity at the fatal region boundary. */
export const STAR_CLUSTER_CORE_EDGE_OPACITY = 0.14

/** Fatal region boundary ring opacity. */
export const STAR_CLUSTER_CORE_STROKE_ALPHA = 0.55

/** Reference alpha used to scale radiation band opacities. */
export const STAR_CLUSTER_CORE_FILL_ALPHA = 0.5

/** Screen-stable halo outline width in pane pixels (finer than other cartography discs). */
export const STAR_CLUSTER_STROKE_WIDTH = 0.5

/** Band opacity at the halo edge where radiation reaches 0. */
export const STAR_CLUSTER_BAND_EDGE_OPACITY =
  0.07 * (STAR_CLUSTER_CORE_FILL_ALPHA / 0.88)

/** Band opacity at the lethal core edge (peak radiation in the halo). */
export const STAR_CLUSTER_BAND_MAX_OPACITY =
  0.5 * (STAR_CLUSTER_CORE_FILL_ALPHA / 0.88)

function lerpChannel(start: number, end: number, t: number): number {
  return Math.round(start + (end - start) * t)
}

function rgbToHex(r: number, g: number, b: number): string {
  const toHex = (channel: number) => channel.toString(16).padStart(2, '0')
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`
}

/** Interpolate star cluster fill from red (cool) to white (hot) on a log temperature scale. */
export function starClusterColorFromTemp(temp: number): string {
  const min = STAR_CLUSTER_TEMP_COLOR_MIN
  const max = STAR_CLUSTER_TEMP_COLOR_MAX
  const safeTemp = Math.max(min, Math.min(max, temp > 0 ? temp : min))
  const t = clamp01(
    (Math.log(safeTemp) - Math.log(min)) / (Math.log(max) - Math.log(min))
  )
  return rgbToHex(
    lerpChannel(STAR_CLUSTER_COOL_RGB[0], STAR_CLUSTER_HOT_RGB[0], t),
    lerpChannel(STAR_CLUSTER_COOL_RGB[1], STAR_CLUSTER_HOT_RGB[1], t),
    lerpChannel(STAR_CLUSTER_COOL_RGB[2], STAR_CLUSTER_HOT_RGB[2], t)
  )
}

/** Radiation halo outer radius in map ly (host: sqrt(mass)). */
export function starClusterHaloRadiusLy(mass: number): number {
  if (!Number.isFinite(mass) || mass <= 0) return 0
  return Math.sqrt(mass)
}

/** Peak radiation at the lethal core edge (matches Core sample_at). */
export function starClusterPeakRadiationAtCoreEdge(
  temp: number,
  coreRadius: number,
  haloRadius: number
): number {
  if (haloRadius <= coreRadius || haloRadius <= 0) return 0
  return (temp / 100) * (1 - coreRadius / haloRadius)
}

export function starClusterCoreHotspotOpacity(): number {
  return STAR_CLUSTER_CORE_HOTSPOT_OPACITY
}

export function starClusterCoreEdgeOpacity(): number {
  return STAR_CLUSTER_CORE_EDGE_OPACITY
}

export function starClusterCoreHotspotRadiusFraction(): number {
  return STAR_CLUSTER_CORE_HOTSPOT_RADIUS_FRACTION
}

export function starClusterCoreStrokeOpacity(): number {
  return STAR_CLUSTER_CORE_STROKE_ALPHA
}

export function starClusterBandEdgeOpacity(): number {
  return STAR_CLUSTER_BAND_EDGE_OPACITY
}

/** Map peak radiation to band fill opacity at the core edge (below lethal core brightness). */
export function starClusterBandPeakOpacity(
  temp: number,
  coreRadius: number,
  haloRadius: number
): number {
  const peakRadiation = starClusterPeakRadiationAtCoreEdge(temp, coreRadius, haloRadius)
  if (peakRadiation <= 0) return STAR_CLUSTER_BAND_EDGE_OPACITY
  const intensity = Math.min(1, peakRadiation / 150)
  return (
    STAR_CLUSTER_BAND_EDGE_OPACITY +
    intensity * (STAR_CLUSTER_BAND_MAX_OPACITY - STAR_CLUSTER_BAND_EDGE_OPACITY)
  )
}

/** Map summed halo flux to raster alpha for neutron cluster overlays. */
export function neutronClusterFluxOpacityFromTotal(totalFlux: number): number {
  if (totalFlux <= 0) return 0
  const intensity = Math.min(1, totalFlux / 150)
  return (
    STAR_CLUSTER_BAND_EDGE_OPACITY +
    intensity * (STAR_CLUSTER_BAND_MAX_OPACITY - STAR_CLUSTER_BAND_EDGE_OPACITY)
  )
}

/** Fixed blue gradient for neutron cluster lethal cores. */
export function neutronClusterCoreColorFromTemp(_temp: number): string {
  const min = STAR_CLUSTER_TEMP_COLOR_MIN
  const max = STAR_CLUSTER_TEMP_COLOR_MAX
  const safeTemp = Math.max(min, Math.min(max, _temp > 0 ? _temp : min))
  const t = clamp01(
    (Math.log(safeTemp) - Math.log(min)) / (Math.log(max) - Math.log(min))
  )
  return rgbToHex(
    lerpChannel(NEUTRON_CLUSTER_CORE_RGB[0], NEUTRON_CLUSTER_CORE_HOT_RGB[0], t),
    lerpChannel(NEUTRON_CLUSTER_CORE_RGB[1], NEUTRON_CLUSTER_CORE_HOT_RGB[1], t),
    lerpChannel(NEUTRON_CLUSTER_CORE_RGB[2], NEUTRON_CLUSTER_CORE_HOT_RGB[2], t)
  )
}

export function neutronClusterCoreHotspotOpacity(): number {
  return STAR_CLUSTER_CORE_HOTSPOT_OPACITY
}

export function neutronClusterCoreEdgeOpacity(): number {
  return STAR_CLUSTER_CORE_EDGE_OPACITY
}

export function neutronClusterCoreStrokeOpacity(): number {
  return STAR_CLUSTER_CORE_STROKE_ALPHA
}

export const BLACK_HOLE_BAND_FILL_ALPHA = 0.25
export const BLACK_HOLE_BAND_RIM_ALPHA = 0.6

/** Wormhole edges render below connection edges (#b1b1b7 at 50%). */
export const WORMHOLE_EDGE_OPACITY = 0.35
