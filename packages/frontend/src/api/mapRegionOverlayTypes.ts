/**
 * Analytic-agnostic map region overlay wire types (hybrid disks + nebula patches).
 * Distinct from Stellar Cartography ``overlayCircles``.
 */

export type MapRegionCoverageRleRun = {
  length: number
  covered: boolean
}

export type MapRegionOverlayDisk = {
  x: number
  y: number
  radius: number
}

export type MapRegionOverlayPatch = {
  originX: number
  originY: number
  width: number
  height: number
  coverageRle: MapRegionCoverageRleRun[]
}

export type MapRegionOverlay = {
  kind: string
  id: string
  fillColor: string
  fillOpacity: number
  disks: MapRegionOverlayDisk[]
  patches: MapRegionOverlayPatch[]
}
