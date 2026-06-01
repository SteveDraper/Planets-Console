import type {
  BlackHoleOverlayCircle,
  DebrisDiskOverlayCircle,
  IonStormOverlayCircle,
  NebulaOverlayCircle,
  NeutronClusterOverlayCircle,
  StarClusterOverlayCircle,
  StellarCartographyOverlayCircle,
} from '../../api/bff'

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
    switch (circle.layer) {
      case 'debris-disks':
        out.debrisDisks.push(circle)
        break
      case 'nebulae':
        out.nebulae.push(circle)
        break
      case 'ion-storms':
        out.ionStorms.push(circle)
        break
      case 'star-clusters':
        out.starClusters.push(circle)
        break
      case 'neutron-clusters':
        out.neutronClusters.push(circle)
        break
      case 'black-holes':
        out.blackHoles.push(circle)
        break
    }
  }
  return out
}
