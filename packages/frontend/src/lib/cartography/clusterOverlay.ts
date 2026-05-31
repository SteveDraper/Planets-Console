import type {
  NeutronClusterOverlayCircle,
  StarClusterOverlayCircle,
} from '../../api/bff'
import {
  circleIntersectsFlowBounds,
  flowBoundsFromViewport,
  flowToPane,
  gameMapCellCenterToFlow,
} from './cartographyOverlayGeometry'
import { hexWithAlpha } from './cartographyColor'
import {
  DISC_RIM_ALPHA,
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
} from './stellarCartographyTheme'
import type {
  StellarCartographyOverlayAnnulusShape,
  StellarCartographyOverlayCircleShape,
  StellarCartographyOverlayRadialGradient,
  StellarCartographyOverlayViewport,
} from './stellarCartographyOverlay'

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

export function buildStarClusterAnnulus(
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

  const { color, coreGradient, coreStroke } = buildClusterCoreGradient(
    temp,
    `sc-core-grad-${circle.id}`,
    starClusterCoreTheme
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

export function buildNeutronClusterCoreCircle(
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

export function buildStarClusterCoreCircle(
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
