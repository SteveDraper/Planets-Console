import type {
  BlackHoleOverlayCircle,
  DebrisDiskOverlayCircle,
  IonStormOverlayCircle,
  NebulaOverlayCircle,
  NeutronClusterOverlayCircle,
  StarClusterOverlayCircle,
  StellarCartographyOverlayCircle,
} from '../../api/bff'
import {
  isBlackHoleOverlayCircle,
  isDebrisDiskOverlayCircle,
  isIonStormOverlayCircle,
  isNebulaOverlayCircle,
  isNeutronClusterOverlayCircle,
  isStarClusterOverlayCircle,
} from '../../api/bffCartographyTypes'

/** Overlay circles grouped by `layer` in a single pass over the wire list. */
export type OverlayCirclesByLayer = {
  debrisDisks: DebrisDiskOverlayCircle[]
  nebulae: NebulaOverlayCircle[]
  ionStorms: IonStormOverlayCircle[]
  starClusters: StarClusterOverlayCircle[]
  neutronClusters: NeutronClusterOverlayCircle[]
  blackHoles: BlackHoleOverlayCircle[]
}

export function groupOverlayCirclesByLayer(
  circles: readonly StellarCartographyOverlayCircle[]
): OverlayCirclesByLayer {
  const out: OverlayCirclesByLayer = {
    debrisDisks: [],
    nebulae: [],
    ionStorms: [],
    starClusters: [],
    neutronClusters: [],
    blackHoles: [],
  }
  for (const circle of circles) {
    if (isDebrisDiskOverlayCircle(circle)) {
      out.debrisDisks.push(circle)
    } else if (isNebulaOverlayCircle(circle)) {
      out.nebulae.push(circle)
    } else if (isIonStormOverlayCircle(circle)) {
      out.ionStorms.push(circle)
    } else if (isStarClusterOverlayCircle(circle)) {
      out.starClusters.push(circle)
    } else if (isNeutronClusterOverlayCircle(circle)) {
      out.neutronClusters.push(circle)
    } else if (isBlackHoleOverlayCircle(circle)) {
      out.blackHoles.push(circle)
    }
  }
  return out
}

/** Star clusters before black holes (paint order for vector annuli / cores). */
export function vectorOverlayCirclesInPaintOrder(
  byLayer: OverlayCirclesByLayer
): Array<StarClusterOverlayCircle | BlackHoleOverlayCircle> {
  return [...byLayer.starClusters, ...byLayer.blackHoles]
}
