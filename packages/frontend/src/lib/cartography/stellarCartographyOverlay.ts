import type {
  IonStormOverlayCircle,
  NeutronClusterOverlayCircle,
  StarClusterOverlayCircle,
  StellarCartographyOverlayCircle,
} from '../../api/bff'
import {
  isBlackHoleOverlayCircle,
  isIonStormOverlayCircle,
  isNebulaOverlayCircle,
  isNeutronClusterOverlayCircle,
  isStarClusterOverlayCircle,
} from '../../api/bffCartographyTypes'
import {
  circleIntersectsFlowBounds,
  flowBoundsFromViewport,
  flowToPane,
  gameMapCellCenterToFlow,
  type CartographyOverlayViewport,
} from './cartographyOverlayGeometry'
import { hexWithAlpha } from './cartographyColor'
import { BLACK_HOLE_CONCEPT_CONSTANTS, buildBlackHolePaneShape, type BlackHolePaneShape } from './blackHoleOverlay'
import { ionStormStepDeltaGameLy } from './ionStormMovement'
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

export type { BlackHolePaneShape } from './blackHoleOverlay'

export type StellarCartographyOverlayPaneShapes = {
  circles: StellarCartographyOverlayCircleShape[]
  annuli: StellarCartographyOverlayAnnulusShape[]
  blackHoles: BlackHolePaneShape[]
  nebulaClouds: NebulaCloudPaneShape[]
  ionStormClouds: IonStormCloudPaneShape[]
  neutronFluxClouds: NeutronClusterFluxPaneShape[]
  /** Debris disk outlines; painted above annuli so borders stay visible. */
  debrisDiskBorders: StellarCartographyOverlayCircleShape[]
  arrows: StellarCartographyOverlayArrowShape[]
  wormholeMarkers: StellarCartographyOverlayWormholeMarkerShape[]
}

export { gameMapCellCenterToFlow } from './cartographyOverlayGeometry'

/** Ion storm movement arrow endpoint in flow space (heading degrees, 0 = north, clockwise). */
export function ionStormArrowEndpointFlow(
  centerGx: number,
  centerGy: number,
  heading: number,
  warp: number | undefined
): { x1: number; y1: number; x2: number; y2: number } {
  const { cx, cy } = gameMapCellCenterToFlow(centerGx, centerGy)
  const { dx, dy: dyGame } = ionStormStepDeltaGameLy(heading, warp)
  return {
    x1: cx,
    y1: cy,
    x2: cx + dx,
    y2: cy - dyGame,
  }
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
  const flowBounds = flowBoundsFromViewport(viewport)
  if (!circleIntersectsFlowBounds(cx, cy, r, flowBounds)) return null

  const { px, py } = flowToPane(cx, cy, viewport)
  const paneR = r * viewport.scale

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

type ClusterCoreGradientTheme = {
  colorFromTemp: (temp: number) => string
  hotspotOpacity: () => number
  edgeOpacity: () => number
  strokeOpacity: () => number
}

function buildClusterCoreGradient(
  temp: number,
  gradientId: string,
  theme: ClusterCoreGradientTheme
): {
  color: string
  coreGradient: StellarCartographyOverlayRadialGradient
  coreStroke: string
} {
  const color = theme.colorFromTemp(temp)
  return {
    color,
    coreGradient: {
      id: gradientId,
      color,
      innerOffset: starClusterCoreHotspotRadiusFraction(),
      peakOpacity: theme.hotspotOpacity(),
      edgeOpacity: theme.edgeOpacity(),
    },
    coreStroke: hexWithAlpha(color, theme.strokeOpacity()),
  }
}

const starClusterCoreTheme: ClusterCoreGradientTheme = {
  colorFromTemp: starClusterColorFromTemp,
  hotspotOpacity: starClusterCoreHotspotOpacity,
  edgeOpacity: starClusterCoreEdgeOpacity,
  strokeOpacity: starClusterCoreStrokeOpacity,
}

const neutronClusterCoreTheme: ClusterCoreGradientTheme = {
  colorFromTemp: neutronClusterCoreColorFromTemp,
  hotspotOpacity: neutronClusterCoreHotspotOpacity,
  edgeOpacity: neutronClusterCoreEdgeOpacity,
  strokeOpacity: neutronClusterCoreStrokeOpacity,
}

function buildClusterCoreCircle(
  circle: { id: string; x: number; y: number; radius: number; temp?: number },
  viewport: StellarCartographyOverlayViewport,
  strokeWidth: number,
  showOutlines: boolean,
  gradientIdPrefix: string,
  theme: ClusterCoreGradientTheme
): StellarCartographyOverlayCircleShape | null {
  const { cx, cy } = gameMapCellCenterToFlow(circle.x, circle.y)
  const r = circle.radius
  const flowBounds = flowBoundsFromViewport(viewport)
  if (!circleIntersectsFlowBounds(cx, cy, r, flowBounds)) return null

  const { px, py } = flowToPane(cx, cy, viewport)
  const { coreGradient, coreStroke } = buildClusterCoreGradient(
    circle.temp ?? 0,
    `${gradientIdPrefix}-core-grad-${circle.id}`,
    theme
  )
  return {
    key: circle.id,
    cx: px,
    cy: py,
    r: r * viewport.scale,
    fill: '',
    fillGradient: coreGradient,
    stroke: showOutlines ? coreStroke : 'none',
    strokeWidth: showOutlines ? strokeWidth : 0,
  }
}

function buildStarClusterCoreGradient(
  circle: StarClusterOverlayCircle,
  gradientId: string
): {
  color: string
  coreGradient: StellarCartographyOverlayRadialGradient
  coreStroke: string
} {
  return buildClusterCoreGradient(circle.temp ?? 0, gradientId, starClusterCoreTheme)
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
  const flowBounds = flowBoundsFromViewport(viewport)
  if (!circleIntersectsFlowBounds(cx, cy, haloRadius, flowBounds)) return null

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
    coreR: coreRadius * viewport.scale,
    bandR: haloRadius * viewport.scale,
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

function buildNeutronClusterCoreCircle(
  circle: NeutronClusterOverlayCircle,
  viewport: StellarCartographyOverlayViewport,
  strokeWidth: number,
  showOutlines: boolean
): StellarCartographyOverlayCircleShape | null {
  return buildClusterCoreCircle(
    circle,
    viewport,
    strokeWidth,
    showOutlines,
    'nc',
    neutronClusterCoreTheme
  )
}

function buildStarClusterCoreCircle(
  circle: StarClusterOverlayCircle,
  viewport: StellarCartographyOverlayViewport,
  strokeWidth: number,
  showOutlines: boolean
): StellarCartographyOverlayCircleShape | null {
  return buildClusterCoreCircle(
    circle,
    viewport,
    strokeWidth,
    showOutlines,
    'sc',
    starClusterCoreTheme
  )
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
    blackHoles: [],
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
  const nebulaCircles = overlayCircles.filter(isNebulaOverlayCircle)
  const nebulaClouds = buildNebulaCloudPaneShapes(nebulaCircles, viewport)
  const ionStormCircles = overlayCircles.filter(isIonStormOverlayCircle)
  const ionStormClouds = buildIonStormCloudPaneShapes(
    ionStormCircles,
    viewport,
    options?.cloudyIonStorms ?? true
  )
  const neutronClusterCircles = overlayCircles.filter(isNeutronClusterOverlayCircle)
  const neutronFluxClouds = buildNeutronClusterFluxPaneShapes(neutronClusterCircles, viewport, {
    showOutlines: areClusterOutlinesShown(options?.neutronClusterDisplayMode ?? 'outlined'),
  })
  const circles: StellarCartographyOverlayCircleShape[] = []
  const annuli: StellarCartographyOverlayAnnulusShape[] = []
  const blackHoles: BlackHolePaneShape[] = []
  const debrisDiskBorders: StellarCartographyOverlayCircleShape[] = []
  const arrows: StellarCartographyOverlayArrowShape[] = []

  type OverlayCirclePaneTarget = {
    circles: StellarCartographyOverlayCircleShape[]
    annuli: StellarCartographyOverlayAnnulusShape[]
    blackHoles: BlackHolePaneShape[]
  }

  const appendOverlayCirclePaneShape = (
    circle: StellarCartographyOverlayCircle,
    target: OverlayCirclePaneTarget
  ): void => {
    if (isBlackHoleOverlayCircle(circle)) {
      const blackHole = buildBlackHolePaneShape(BLACK_HOLE_CONCEPT_CONSTANTS, circle, viewport)
      if (blackHole != null) target.blackHoles.push(blackHole)
      return
    }
    if (isStarClusterOverlayCircle(circle)) {
      const annulus = buildStarClusterAnnulus(
        circle,
        viewport,
        STAR_CLUSTER_STROKE_WIDTH,
        starClusterOutlines
      )
      if (annulus != null) {
        target.annuli.push(annulus)
        return
      }
      const core = buildStarClusterCoreCircle(
        circle,
        viewport,
        STAR_CLUSTER_STROKE_WIDTH,
        starClusterOutlines
      )
      if (core != null) target.circles.push(core)
    }
  }

  const paneTarget: OverlayCirclePaneTarget = { circles, annuli, blackHoles }
  for (const circle of sortOverlayCircles(
    overlayCircles.filter(
      (entry) =>
        entry.layer !== 'nebulae' &&
        entry.layer !== 'debris-disks' &&
        entry.layer !== 'ion-storms' &&
        entry.layer !== 'neutron-clusters'
    )
  )) {
    appendOverlayCirclePaneShape(circle, paneTarget)
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
    blackHoles,
    nebulaClouds,
    ionStormClouds,
    neutronFluxClouds,
    debrisDiskBorders,
    arrows,
    wormholeMarkers,
  }
}
