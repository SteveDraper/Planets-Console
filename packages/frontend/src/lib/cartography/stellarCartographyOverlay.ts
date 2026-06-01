import type {
  DebrisDiskOverlayCircle,
  IonStormOverlayCircle,
  StellarCartographyOverlayCircle,
} from '../../api/bff'
import {
  areClusterOutlinesShown,
  defaultNeutronClusterDisplayMode,
  defaultStarClusterDisplayMode,
  type ClusterOutlineDisplayMode,
} from '../../analytics/stellar-cartography/clusterOutlineDisplayMode'
import {
  circleIntersectsFlowBounds,
  flowBoundsFromViewport,
  flowToPane,
  gameMapCellCenterToFlow,
  type CartographyOverlayViewport,
} from './cartographyOverlayGeometry'
import type {
  StellarCartographyOverlayAnnulusShape,
  StellarCartographyOverlayArrowShape,
  StellarCartographyOverlayCircleShape,
  StellarCartographyOverlayPaneShapes,
  StellarCartographyOverlayWormholeMarkerShape,
} from './cartographyPaneShapes'
import {
  buildNeutronClusterCoreCircle,
  buildStarClusterAnnulus,
  buildStarClusterCoreCircle,
} from './clusterOverlay'
import { BLACK_HOLE_CONCEPT_CONSTANTS, buildBlackHolePaneShape, type BlackHolePaneShape } from './blackHoleOverlay'
import { ionStormStepDeltaGameLy } from './ionStormMovement'
import { buildNebulaCloudPaneShapes } from './nebulaCloudOverlay'
import { buildIonStormCloudPaneShapes } from './ionStormCloudOverlay'
import { buildNeutronClusterFluxPaneShapes } from './neutronClusterFluxOverlay'
import { groupOverlayCirclesByLayer } from './overlayCirclesByLayer'
import {
  DEBRIS_DISK_BORDER_STROKE,
  DEBRIS_DISK_BORDER_STROKE_WIDTH,
  ionStormStrokeColor,
  STAR_CLUSTER_STROKE_WIDTH,
  WORMHOLE_ENDPOINT_DIAMETER_LY,
  WORMHOLE_ENDPOINT_MIN_DIAMETER_PX,
} from './stellarCartographyTheme'

export type {
  StellarCartographyOverlayAnnulusBandGradient,
  StellarCartographyOverlayAnnulusShape,
  StellarCartographyOverlayArrowShape,
  StellarCartographyOverlayCircleShape,
  StellarCartographyOverlayPaneShapes,
  StellarCartographyOverlayRadialGradient,
  StellarCartographyOverlayWormholeMarkerShape,
} from './cartographyPaneShapes'

export type { BlackHolePaneShape } from './blackHoleOverlay'

/** Map span in light-years to pane pixel extent (same projection as warp wells and annuli). */
export function flowLySpanToPanePixels(
  flowCx: number,
  flowCy: number,
  spanLy: number,
  viewport: CartographyOverlayViewport
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
  viewport: CartographyOverlayViewport
): number {
  const mapScaled = flowLySpanToPanePixels(
    flowCx,
    flowCy,
    WORMHOLE_ENDPOINT_DIAMETER_LY,
    viewport
  )
  return Math.max(mapScaled, WORMHOLE_ENDPOINT_MIN_DIAMETER_PX)
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

function buildDebrisDiskBorderShape(
  circle: DebrisDiskOverlayCircle,
  viewport: CartographyOverlayViewport
): StellarCartographyOverlayCircleShape | null {
  const { cx, cy } = gameMapCellCenterToFlow(circle.x, circle.y)
  const r = circle.radius
  const flowBounds = flowBoundsFromViewport(viewport)
  if (!circleIntersectsFlowBounds(cx, cy, r, flowBounds)) return null

  const { px, py } = flowToPane(cx, cy, viewport)
  const paneR = r * viewport.scale

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

function buildIonStormArrow(
  storm: IonStormOverlayCircle,
  viewport: CartographyOverlayViewport,
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
  viewport: CartographyOverlayViewport,
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

  const byLayer = groupOverlayCirclesByLayer(overlayCircles)
  const strokeWidth = 1
  const starClusterOutlines = areClusterOutlinesShown(
    options?.starClusterDisplayMode ?? defaultStarClusterDisplayMode()
  )
  const neutronClusterOutlines = areClusterOutlinesShown(
    options?.neutronClusterDisplayMode ?? defaultNeutronClusterDisplayMode()
  )

  const nebulaClouds = buildNebulaCloudPaneShapes(byLayer.nebulae, viewport)
  const ionStormClouds = buildIonStormCloudPaneShapes(
    byLayer.ionStorms,
    viewport,
    options?.cloudyIonStorms ?? true
  )
  const neutronFluxClouds = buildNeutronClusterFluxPaneShapes(byLayer.neutronClusters, viewport, {
    showOutlines: neutronClusterOutlines,
  })

  const circles: StellarCartographyOverlayCircleShape[] = []
  const annuli: StellarCartographyOverlayAnnulusShape[] = []
  const blackHoles: BlackHolePaneShape[] = []
  const debrisDiskBorders: StellarCartographyOverlayCircleShape[] = []
  const arrows: StellarCartographyOverlayArrowShape[] = []

  for (const circle of byLayer.starClusters) {
    const annulus = buildStarClusterAnnulus(
      circle,
      viewport,
      STAR_CLUSTER_STROKE_WIDTH,
      starClusterOutlines
    )
    if (annulus != null) {
      annuli.push(annulus)
      continue
    }
    const core = buildStarClusterCoreCircle(
      circle,
      viewport,
      STAR_CLUSTER_STROKE_WIDTH,
      starClusterOutlines
    )
    if (core != null) circles.push(core)
  }

  for (const circle of byLayer.blackHoles) {
    const blackHole = buildBlackHolePaneShape(BLACK_HOLE_CONCEPT_CONSTANTS, circle, viewport)
    if (blackHole != null) blackHoles.push(blackHole)
  }

  for (const circle of byLayer.neutronClusters) {
    const core = buildNeutronClusterCoreCircle(
      circle,
      viewport,
      STAR_CLUSTER_STROKE_WIDTH,
      neutronClusterOutlines
    )
    if (core != null) circles.push(core)
  }

  for (const circle of byLayer.ionStorms) {
    if ((circle.parentId ?? 0) !== 0) continue
    const arrow = buildIonStormArrow(circle, viewport, strokeWidth)
    if (arrow != null) arrows.push(arrow)
  }

  for (const circle of byLayer.debrisDisks) {
    const shape = buildDebrisDiskBorderShape(circle, viewport)
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
