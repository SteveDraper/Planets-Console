import type { BlackHoleOverlayCircle } from '../../api/bff'
import {
  circleIntersectsFlowBounds,
  flowBoundsFromViewport,
  flowToPane,
  gameMapCellCenterToFlow,
  type CartographyOverlayViewport,
} from './cartographyOverlayGeometry'
import {
  BLACK_HOLE_CORE_FILL,
  BLACK_HOLE_ERGOSPHERE_BAND_OPACITY,
  blackHoleErgosphereBandGrey,
} from './stellarCartographyTheme'

/** Planets.nu-aligned black hole overlay geometry (ergosphere bands, cosmetic halo). */
export type BlackHoleConceptConstants = {
  ergosphereBandCount: number
  haloExtraLy: number
}

/** Contract: test-fixtures/black-hole-ergosphere-contract.json */
export const BLACK_HOLE_CONCEPT_CONSTANTS = {
  ergosphereBandCount: 9,
  haloExtraLy: 5,
} satisfies BlackHoleConceptConstants

export type BlackHoleErgosphereGradientStop = {
  /** Fraction of ergosphere radius from center (0–1). */
  offset: number
  color: string
  opacity: number
}

/** One pane-pixel black hole: ergosphere radial gradient plus outer cyan halo. */
export type BlackHolePaneShape = {
  key: string
  cx: number
  cy: number
  coreR: number
  ergosphereR: number
  haloR: number
  /** Fraction of halo radius where ergosphere ends and cyan glow begins. */
  ergosphereEdgeOffset: number
  ergosphereGradientId: string
  haloGradientId: string
  ergosphereStops: readonly BlackHoleErgosphereGradientStop[]
}

/** Inner and outer ergosphere band edges in ly (band 1 = innermost). Visual gradient only. */
function blackHoleBandRadiiLy(
  coreRadiusLy: number,
  bandWidthLy: number,
  band: number
): { innerLy: number; outerLy: number } {
  return {
    innerLy: coreRadiusLy + (band - 1) * bandWidthLy,
    outerLy: coreRadiusLy + band * bandWidthLy,
  }
}

/** Radial gradient stops matching host ergosphere band greys. */
export function buildBlackHoleErgosphereGradientStops(
  constants: BlackHoleConceptConstants,
  coreRadiusLy: number,
  bandWidthLy: number,
  outerLy: number
): BlackHoleErgosphereGradientStop[] {
  if (outerLy <= 0) {
    return []
  }

  const { ergosphereBandCount } = constants
  const stops: BlackHoleErgosphereGradientStop[] = [
    { offset: 0, color: BLACK_HOLE_CORE_FILL, opacity: 1 },
  ]

  const coreOffset = Math.min(1, coreRadiusLy / outerLy)
  if (coreRadiusLy > 0) {
    stops.push({ offset: coreOffset, color: BLACK_HOLE_CORE_FILL, opacity: 1 })
    stops.push({
      offset: coreOffset,
      color: blackHoleErgosphereBandGrey(1, ergosphereBandCount),
      opacity: BLACK_HOLE_ERGOSPHERE_BAND_OPACITY,
    })
  } else {
    stops.push({
      offset: 0,
      color: blackHoleErgosphereBandGrey(1, ergosphereBandCount),
      opacity: BLACK_HOLE_ERGOSPHERE_BAND_OPACITY,
    })
  }

  for (let band = 2; band <= ergosphereBandCount; band++) {
    const { innerLy } = blackHoleBandRadiiLy(coreRadiusLy, bandWidthLy, band)
    const offset = Math.min(1, innerLy / outerLy)
    stops.push({
      offset,
      color: blackHoleErgosphereBandGrey(band - 1, ergosphereBandCount),
      opacity: BLACK_HOLE_ERGOSPHERE_BAND_OPACITY,
    })
    stops.push({
      offset,
      color: blackHoleErgosphereBandGrey(band, ergosphereBandCount),
      opacity: BLACK_HOLE_ERGOSPHERE_BAND_OPACITY,
    })
  }

  stops.push({
    offset: 1,
    color: blackHoleErgosphereBandGrey(ergosphereBandCount, ergosphereBandCount),
    opacity: BLACK_HOLE_ERGOSPHERE_BAND_OPACITY,
  })

  return stops
}

export function buildBlackHolePaneShape(
  constants: BlackHoleConceptConstants,
  circle: BlackHoleOverlayCircle,
  viewport: CartographyOverlayViewport
): BlackHolePaneShape | null {
  const { cx, cy } = gameMapCellCenterToFlow(circle.x, circle.y)
  const outerLy = circle.radius
  const haloLy = circle.radius + constants.haloExtraLy
  const flowBounds = flowBoundsFromViewport(viewport)
  if (!circleIntersectsFlowBounds(cx, cy, haloLy, flowBounds)) {
    return null
  }

  const { px, py } = flowToPane(cx, cy, viewport)
  const scale = viewport.scale

  return {
    key: circle.id,
    cx: px,
    cy: py,
    coreR: circle.coreRadius * scale,
    ergosphereR: outerLy * scale,
    haloR: haloLy * scale,
    ergosphereEdgeOffset: outerLy / haloLy,
    ergosphereGradientId: `${circle.id}-ergo-grad`,
    haloGradientId: `${circle.id}-halo-grad`,
    ergosphereStops: buildBlackHoleErgosphereGradientStops(
      constants,
      circle.coreRadius,
      circle.bandRadius,
      outerLy
    ),
  }
}
