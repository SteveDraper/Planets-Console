import type {
  BlackHoleOverlayCircle,
  IonStormOverlayCircle,
  NebulaOverlayCircle,
  NeutronClusterOverlayCircle,
  StarClusterOverlayCircle,
  StellarCartographyOverlayCircle,
} from '../../api/bff'
import {
  flowToPane,
  gameMapCellCenterToFlow,
  type CartographyOverlayViewport,
} from './cartographyOverlayGeometry'
import { buildNebulaCloudPaneShapes, type NebulaCloudPaneShape } from './nebulaCloudOverlay'
import {
  buildIonStormCloudPaneShapes,
  type IonStormCloudPaneShape,
} from './ionStormCloudOverlay'
import {
  buildNeutronClusterFluxPaneShapes,
  type NeutronClusterFluxPaneShape,
} from './neutronClusterFluxOverlay'
import { areClusterOutlinesShown, type ClusterOutlineDisplayMode } from '../../analytics/stellar-cartography/clusterOutlineDisplayMode'
import {
  BLACK_HOLE_BAND_FILL,
  BLACK_HOLE_BAND_FILL_ALPHA,
  BLACK_HOLE_BAND_RIM_ALPHA,
  BLACK_HOLE_BAND_STROKE,
  BLACK_HOLE_CORE_FILL,
  DEBRIS_DISK_BORDER_STROKE,
  DEBRIS_DISK_BORDER_STROKE_WIDTH,
  DISC_RIM_ALPHA,
  ionStormStrokeColor,
  neutronClusterCoreColorFromTemp,
  neutronClusterCoreEdgeOpacity,
  neutronClusterCoreHotspotOpacity,
  neutronClusterCoreStrokeOpacity,
  starClusterBandEdgeOpacity,
  starClusterBandPeakOpacity,
  starClusterColorFromTemp,
  starClusterCoreEdgeOpacity,
  starClusterCoreHotspotOpacity,
  starClusterCoreHotspotRadiusFraction,
  starClusterCoreStrokeOpacity,
  starClusterHaloRadiusLy,
  STAR_CLUSTER_STROKE_WIDTH,
  WORMHOLE_ENDPOINT_DIAMETER_LY,
  WORMHOLE_ENDPOINT_MIN_DIAMETER_PX,
} from './stellarCartographyTheme'

export type StellarCartographyOverlayViewport = CartographyOverlayViewport

export type StellarCartographyOverlayCircleShape = {
  key: string
  cx: number
  cy: number
  r: number
  fill: string
  stroke: string
  strokeWidth: number
  fillGradient?: StellarCartographyOverlayRadialGradient
}

export type StellarCartographyOverlayRadialGradient = {
  id: string
  color: string
  innerOffset: number
  peakOpacity: number
  edgeOpacity: number
}

/** Radiation halo gradient: transparent until core edge, then peak to edge opacity. */
export type StellarCartographyOverlayAnnulusBandGradient = StellarCartographyOverlayRadialGradient

export type StellarCartographyOverlayAnnulusShape = {
  key: string
  cx: number
  cy: number
  coreR: number
  bandR: number
  coreFill: string
  coreStroke?: string
  coreGradient?: StellarCartographyOverlayRadialGradient
  bandFill: string
  bandStroke: string
  strokeWidth: number
  bandGradient?: StellarCartographyOverlayAnnulusBandGradient
}

export type StellarCartographyOverlayArrowShape = {
  key: string
  x1: number
  y1: number
  x2: number
  y2: number
  stroke: string
  strokeWidth: number
}

/** Map span in light-years to pane pixel extent (same projection as warp wells and annuli). */
export function flowLySpanToPanePixels(
  flowCx: number,
  flowCy: number,
  spanLy: number,
  viewport: StellarCartographyOverlayViewport
): number {
  const half = spanLy / 2
  const a = flowToPane(flowCx - half, flowCy, viewport)
  const b = flowToPane(flowCx + half, flowCy, viewport)
  return Math.hypot(b.px - a.px, b.py - a.py)
}

/** Map-scaled wormhole icon diameter in pane pixels, floored at the 300% slider size. */
export function wormholeEndpointDiameterPx(
  flowCx: number,
  flowCy: number,
  viewport: StellarCartographyOverlayViewport
): number {
  const mapScaled = flowLySpanToPanePixels(
    flowCx,
    flowCy,
    WORMHOLE_ENDPOINT_DIAMETER_LY,
    viewport
  )
  return Math.max(mapScaled, WORMHOLE_ENDPOINT_MIN_DIAMETER_PX)
}

export type StellarCartographyOverlayWormholeMarkerShape = {
  key: string
  cx: number
  cy: number
  diameterPx: number
  mapX: number
  mapY: number
}

export type StellarCartographyOverlayPaneShapes = {
  circles: StellarCartographyOverlayCircleShape[]
  annuli: StellarCartographyOverlayAnnulusShape[]
  nebulaClouds: NebulaCloudPaneShape[]
  ionStormClouds: IonStormCloudPaneShape[]
  neutronFluxClouds: NeutronClusterFluxPaneShape[]
  /** Debris disk outlines; painted above annuli so borders stay visible. */
  debrisDiskBorders: StellarCartographyOverlayCircleShape[]
  arrows: StellarCartographyOverlayArrowShape[]
  wormholeMarkers: StellarCartographyOverlayWormholeMarkerShape[]
}

export { gameMapCellCenterToFlow } from './cartographyOverlayGeometry'

function ionStormMovementLengthLy(warp: number | undefined): number {
  const w = warp ?? 0
  return w * w
}

/** Ion storm movement arrow endpoint in flow space (heading degrees, 0 = north, clockwise). */
export function ionStormArrowEndpointFlow(
  centerGx: number,
  centerGy: number,
  heading: number,
  warp: number | undefined
): { x1: number; y1: number; x2: number; y2: number } {
  const { cx, cy } = gameMapCellCenterToFlow(centerGx, centerGy)
  const lengthLy = ionStormMovementLengthLy(warp)
  const theta = (heading * Math.PI) / 180
  const dx = Math.sin(theta) * lengthLy
  const dyGame = Math.cos(theta) * lengthLy
  return {
    x1: cx,
    y1: cy,
    x2: cx + dx,
    y2: cy - dyGame,
  }
}

function circleIntersectsViewport(
  cx: number,
  cy: number,
  r: number,
  fxMin: number,
  fxMax: number,
  fyMin: number,
  fyMax: number
): boolean {
  const closestX = Math.max(fxMin, Math.min(cx, fxMax))
  const closestY = Math.max(fyMin, Math.min(cy, fyMax))
  const distSq = (cx - closestX) ** 2 + (cy - closestY) ** 2
  return distSq <= r * r
}

function sortOverlayCircles(
  circles: readonly StellarCartographyOverlayCircle[]
): StellarCartographyOverlayCircle[] {
  const order: Record<string, number> = {
    'debris-disks': -1,
    nebulae: 0,
    'ion-storms': 1,
    'star-clusters': 2,
    'neutron-clusters': 2,
    'black-holes': 3,
  }
  return [...circles].sort(
    (a, b) => (order[a.layer] ?? 99) - (order[b.layer] ?? 99)
  )
}

function buildCircleShape(
  circle: StellarCartographyOverlayCircle,
  viewport: StellarCartographyOverlayViewport,
  _strokeWidth: number
): StellarCartographyOverlayCircleShape | null {
  const { cx, cy } = gameMapCellCenterToFlow(circle.x, circle.y)
  const r = circle.radius
  const { scale } = viewport
  const fxMin = -viewport.tx / scale
  const fxMax = (viewport.width - viewport.tx) / scale
  const fyMin = -viewport.ty / scale
  const fyMax = (viewport.height - viewport.ty) / scale
  if (!circleIntersectsViewport(cx, cy, r, fxMin, fxMax, fyMin, fyMax)) return null

  const { px, py } = flowToPane(cx, cy, viewport)
  const paneR = r * scale

  if (circle.layer === 'debris-disks') {
    return {
      key: circle.id,
      cx: px,
      cy: py,
      r: paneR,
      fill: 'none',
      stroke: DEBRIS_DISK_BORDER_STROKE,
      strokeWidth: DEBRIS_DISK_BORDER_STROKE_WIDTH,
    }
  }

  return null
}

function buildStarClusterCoreGradient(
  circle: StarClusterOverlayCircle,
  gradientId: string
): {
  color: string
  coreGradient: StellarCartographyOverlayRadialGradient
  coreStroke: string
} {
  const color = starClusterColorFromTemp(circle.temp ?? 0)
  return {
    color,
    coreGradient: {
      id: gradientId,
      color,
      innerOffset: starClusterCoreHotspotRadiusFraction(),
      peakOpacity: starClusterCoreHotspotOpacity(),
      edgeOpacity: starClusterCoreEdgeOpacity(),
    },
    coreStroke: hexWithAlpha(color, starClusterCoreStrokeOpacity()),
  }
}

function buildStarClusterAnnulus(
  circle: StarClusterOverlayCircle,
  viewport: StellarCartographyOverlayViewport,
  strokeWidth: number,
  showOutlines: boolean
): StellarCartographyOverlayAnnulusShape | null {
  const coreRadius = circle.radius
  const haloRadius = starClusterHaloRadiusLy(circle.mass ?? 0)
  if (haloRadius <= coreRadius) return null

  const { cx, cy } = gameMapCellCenterToFlow(circle.x, circle.y)
  const { scale } = viewport
  const fxMin = -viewport.tx / scale
  const fxMax = (viewport.width - viewport.tx) / scale
  const fyMin = -viewport.ty / scale
  const fyMax = (viewport.height - viewport.ty) / scale
  if (!circleIntersectsViewport(cx, cy, haloRadius, fxMin, fxMax, fyMin, fyMax)) return null

  const { px, py } = flowToPane(cx, cy, viewport)
  const temp = circle.temp ?? 0
  const peakOpacity = starClusterBandPeakOpacity(temp, coreRadius, haloRadius)
  const edgeOpacity = starClusterBandEdgeOpacity()
  if (peakOpacity <= edgeOpacity) return null

  const { color, coreGradient, coreStroke } = buildStarClusterCoreGradient(
    circle,
    `sc-core-grad-${circle.id}`
  )

  return {
    key: circle.id,
    cx: px,
    cy: py,
    coreR: coreRadius * scale,
    bandR: haloRadius * scale,
    coreFill: '',
    coreStroke: showOutlines ? coreStroke : undefined,
    coreGradient,
    bandFill: '',
    bandStroke: showOutlines ? hexWithAlpha(color, DISC_RIM_ALPHA) : 'none',
    strokeWidth,
    bandGradient: {
      id: `sc-band-grad-${circle.id}`,
      color,
      innerOffset: coreRadius / haloRadius,
      peakOpacity,
      edgeOpacity,
    },
  }
}

function buildNeutronClusterCoreGradient(
  circle: NeutronClusterOverlayCircle,
  gradientId: string
): {
  color: string
  coreGradient: StellarCartographyOverlayRadialGradient
  coreStroke: string
} {
  const color = neutronClusterCoreColorFromTemp(circle.temp ?? 0)
  return {
    color,
    coreGradient: {
      id: gradientId,
      color,
      innerOffset: starClusterCoreHotspotRadiusFraction(),
      peakOpacity: neutronClusterCoreHotspotOpacity(),
      edgeOpacity: neutronClusterCoreEdgeOpacity(),
    },
    coreStroke: hexWithAlpha(color, neutronClusterCoreStrokeOpacity()),
  }
}

function buildNeutronClusterCoreCircle(
  circle: NeutronClusterOverlayCircle,
  viewport: StellarCartographyOverlayViewport,
  strokeWidth: number,
  showOutlines: boolean
): StellarCartographyOverlayCircleShape | null {
  const { cx, cy } = gameMapCellCenterToFlow(circle.x, circle.y)
  const r = circle.radius
  const { scale } = viewport
  const fxMin = -viewport.tx / scale
  const fxMax = (viewport.width - viewport.tx) / scale
  const fyMin = -viewport.ty / scale
  const fyMax = (viewport.height - viewport.ty) / scale
  if (!circleIntersectsViewport(cx, cy, r, fxMin, fxMax, fyMin, fyMax)) return null

  const { px, py } = flowToPane(cx, cy, viewport)
  const { coreGradient, coreStroke } = buildNeutronClusterCoreGradient(
    circle,
    `nc-core-grad-${circle.id}`
  )
  return {
    key: circle.id,
    cx: px,
    cy: py,
    r: r * scale,
    fill: '',
    fillGradient: coreGradient,
    stroke: showOutlines ? coreStroke : 'none',
    strokeWidth: showOutlines ? strokeWidth : 0,
  }
}

function buildStarClusterCoreCircle(
  circle: StarClusterOverlayCircle,
  viewport: StellarCartographyOverlayViewport,
  strokeWidth: number,
  showOutlines: boolean
): StellarCartographyOverlayCircleShape | null {
  const { cx, cy } = gameMapCellCenterToFlow(circle.x, circle.y)
  const r = circle.radius
  const { scale } = viewport
  const fxMin = -viewport.tx / scale
  const fxMax = (viewport.width - viewport.tx) / scale
  const fyMin = -viewport.ty / scale
  const fyMax = (viewport.height - viewport.ty) / scale
  if (!circleIntersectsViewport(cx, cy, r, fxMin, fxMax, fyMin, fyMax)) return null

  const { px, py } = flowToPane(cx, cy, viewport)
  const { coreGradient, coreStroke } = buildStarClusterCoreGradient(
    circle,
    `sc-core-grad-${circle.id}`
  )
  return {
    key: circle.id,
    cx: px,
    cy: py,
    r: r * scale,
    fill: '',
    fillGradient: coreGradient,
    stroke: showOutlines ? coreStroke : 'none',
    strokeWidth: showOutlines ? strokeWidth : 0,
  }
}

function buildBlackHoleAnnulus(
  circle: BlackHoleOverlayCircle,
  viewport: StellarCartographyOverlayViewport,
  strokeWidth: number
): StellarCartographyOverlayAnnulusShape | null {
  const { cx, cy } = gameMapCellCenterToFlow(circle.x, circle.y)
  const bandR = circle.bandRadius
  const { scale } = viewport
  const fxMin = -viewport.tx / scale
  const fxMax = (viewport.width - viewport.tx) / scale
  const fyMin = -viewport.ty / scale
  const fyMax = (viewport.height - viewport.ty) / scale
  if (!circleIntersectsViewport(cx, cy, bandR, fxMin, fxMax, fyMin, fyMax)) return null

  const { px, py } = flowToPane(cx, cy, viewport)
  return {
    key: circle.id,
    cx: px,
    cy: py,
    coreR: circle.coreRadius * scale,
    bandR: bandR * scale,
    coreFill: BLACK_HOLE_CORE_FILL,
    bandFill: hexWithAlpha(BLACK_HOLE_BAND_FILL, BLACK_HOLE_BAND_FILL_ALPHA),
    bandStroke: hexWithAlpha(BLACK_HOLE_BAND_STROKE, BLACK_HOLE_BAND_RIM_ALPHA),
    strokeWidth,
  }
}

function buildIonStormArrow(
  storm: IonStormOverlayCircle,
  viewport: StellarCartographyOverlayViewport,
  strokeWidth: number
): StellarCartographyOverlayArrowShape | null {
  if (storm.heading == null || storm.warp == null || storm.warp <= 0) return null
  const { x1, y1, x2, y2 } = ionStormArrowEndpointFlow(
    storm.x,
    storm.y,
    storm.heading,
    storm.warp
  )
  const start = flowToPane(x1, y1, viewport)
  const end = flowToPane(x2, y2, viewport)
  const stormClass = storm.class
  return {
    key: `${storm.id}-arrow`,
    x1: start.px,
    y1: start.py,
    x2: end.px,
    y2: end.py,
    stroke: ionStormStrokeColor(stormClass),
    strokeWidth,
  }
}

function hexWithAlpha(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/** Build pane-pixel SVG shapes for Stellar Cartography overlays at the given zoom. */
export function buildStellarCartographyOverlayPaneShapes(
  overlayCircles: readonly StellarCartographyOverlayCircle[],
  wormholeEndpoints: readonly { x: number; y: number }[],
  viewport: StellarCartographyOverlayViewport,
  options?: {
    cloudyIonStorms?: boolean
    starClusterDisplayMode?: ClusterOutlineDisplayMode
    neutronClusterDisplayMode?: ClusterOutlineDisplayMode
  }
): StellarCartographyOverlayPaneShapes {
  const { width, height, scale } = viewport
  const empty: StellarCartographyOverlayPaneShapes = {
    circles: [],
    annuli: [],
    nebulaClouds: [],
    ionStormClouds: [],
    neutronFluxClouds: [],
    debrisDiskBorders: [],
    arrows: [],
    wormholeMarkers: [],
  }
  if (width <= 0 || height <= 0 || !Number.isFinite(scale) || scale <= 0) {
    return empty
  }

  const strokeWidth = 1
  const starClusterOutlines = areClusterOutlinesShown(
    options?.starClusterDisplayMode ?? 'outlined'
  )
  const neutronClusterOutlines = areClusterOutlinesShown(
    options?.neutronClusterDisplayMode ?? 'outlined'
  )
  const nebulaCircles = overlayCircles.filter(
    (circle): circle is NebulaOverlayCircle => circle.layer === 'nebulae'
  )
  const nebulaClouds = buildNebulaCloudPaneShapes(nebulaCircles, viewport)
  const ionStormCircles = overlayCircles.filter(
    (circle): circle is IonStormOverlayCircle => circle.layer === 'ion-storms'
  )
  const ionStormClouds = buildIonStormCloudPaneShapes(
    ionStormCircles,
    viewport,
    options?.cloudyIonStorms ?? true
  )
  const neutronClusterCircles = overlayCircles.filter(
    (circle): circle is NeutronClusterOverlayCircle => circle.layer === 'neutron-clusters'
  )
  const neutronFluxClouds = buildNeutronClusterFluxPaneShapes(neutronClusterCircles, viewport, {
    showOutlines: areClusterOutlinesShown(options?.neutronClusterDisplayMode ?? 'outlined'),
  })
  const circles: StellarCartographyOverlayCircleShape[] = []
  const annuli: StellarCartographyOverlayAnnulusShape[] = []
  const debrisDiskBorders: StellarCartographyOverlayCircleShape[] = []
  const arrows: StellarCartographyOverlayArrowShape[] = []

  for (const circle of sortOverlayCircles(
    overlayCircles.filter(
      (entry) =>
        entry.layer !== 'nebulae' &&
        entry.layer !== 'debris-disks' &&
        entry.layer !== 'ion-storms' &&
        entry.layer !== 'neutron-clusters'
    )
  )) {
    if (circle.layer === 'black-holes') {
      const annulus = buildBlackHoleAnnulus(circle as BlackHoleOverlayCircle, viewport, strokeWidth)
      if (annulus != null) annuli.push(annulus)
      continue
    }
    if (circle.layer === 'star-clusters') {
      const star = circle as StarClusterOverlayCircle
      const annulus = buildStarClusterAnnulus(
        star,
        viewport,
        STAR_CLUSTER_STROKE_WIDTH,
        starClusterOutlines
      )
      if (annulus != null) {
        annuli.push(annulus)
        continue
      }
      const core = buildStarClusterCoreCircle(
        star,
        viewport,
        STAR_CLUSTER_STROKE_WIDTH,
        starClusterOutlines
      )
      if (core != null) circles.push(core)
      continue
    }
    const shape = buildCircleShape(circle, viewport, strokeWidth)
    if (shape != null) circles.push(shape)
  }

  for (const circle of neutronClusterCircles) {
    const core = buildNeutronClusterCoreCircle(
      circle,
      viewport,
      STAR_CLUSTER_STROKE_WIDTH,
      neutronClusterOutlines
    )
    if (core != null) circles.push(core)
  }

  for (const circle of ionStormCircles) {
    if ((circle.parentId ?? 0) !== 0) continue
    const arrow = buildIonStormArrow(circle, viewport, strokeWidth)
    if (arrow != null) arrows.push(arrow)
  }

  for (const circle of overlayCircles) {
    if (circle.layer !== 'debris-disks') continue
    const shape = buildCircleShape(circle, viewport, DEBRIS_DISK_BORDER_STROKE_WIDTH)
    if (shape != null) debrisDiskBorders.push(shape)
  }

  const wormholeMarkers: StellarCartographyOverlayWormholeMarkerShape[] = []
  const seenEndpoints = new Set<string>()
  for (const endpoint of wormholeEndpoints) {
    const key = `${endpoint.x},${endpoint.y}`
    if (seenEndpoints.has(key)) continue
    seenEndpoints.add(key)
    const { cx, cy } = gameMapCellCenterToFlow(endpoint.x, endpoint.y)
    const { px, py } = flowToPane(cx, cy, viewport)
    const diameterPx = wormholeEndpointDiameterPx(cx, cy, viewport)
    wormholeMarkers.push({
      key: `wh-${endpoint.x}-${endpoint.y}`,
      cx: px,
      cy: py,
      diameterPx,
      mapX: endpoint.x,
      mapY: endpoint.y,
    })
  }

  return {
    circles,
    annuli,
    nebulaClouds,
    ionStormClouds,
    neutronFluxClouds,
    debrisDiskBorders,
    arrows,
    wormholeMarkers,
  }
}
