import type { BlackHolePaneShape } from './blackHoleOverlay'
import type { IonStormCloudPaneShape } from './ionStormCloudOverlay'
import type { NebulaCloudPaneShape } from './nebulaCloudOverlay'
import type { NeutronClusterFluxPaneShape } from './neutronClusterFluxOverlay'

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
  blackHoles: BlackHolePaneShape[]
  nebulaClouds: NebulaCloudPaneShape[]
  ionStormClouds: IonStormCloudPaneShape[]
  neutronFluxClouds: NeutronClusterFluxPaneShape[]
  /** Debris disk outlines; painted above annuli so borders stay visible. */
  debrisDiskBorders: StellarCartographyOverlayCircleShape[]
  arrows: StellarCartographyOverlayArrowShape[]
  wormholeMarkers: StellarCartographyOverlayWormholeMarkerShape[]
}
