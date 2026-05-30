import type { NeutronClusterOverlayCircle } from '../api/bff'
import {
  boundaryPathsFromMapPolygons,
  boundsIntersectsViewport,
  mapBoundsFromCircles,
  paneRectFromBounds,
  type CartographyOverlayViewport,
  type MapBounds,
  type MapPoint,
} from './cartographyOverlayGeometry'
import { rasterizeMapField } from './rasterizeMapField'
import { mapCellUnionBoundaryPolylines } from './mapCellUnionBoundary'
import { mapLyToSampleCell } from '../planetSpatialGrid'
import {
  starClusterHaloRadiusLy,
  starClusterRadiationSumAt,
  type StarClusterRadiationBody,
} from './starClusterRadiation'
import {
  DISC_RIM_ALPHA,
  NEUTRON_CLUSTER_FLUX_MAX_RASTER_PX,
  NEUTRON_CLUSTER_FLUX_RGB,
  neutronClusterCoreColorFromTemp,
  neutronClusterFluxOpacityFromTotal,
  STAR_CLUSTER_STROKE_WIDTH,
} from './stellarCartographyTheme'

export type NeutronClusterFluxPaneShape = {
  key: string
  left: number
  top: number
  width: number
  height: number
  imageDataUrl: string
  fillClipPathId: string
  boundaryPaths: string[]
  stroke: string
  strokeWidth: number
}

type NeutronClusterFluxGeometryCache = {
  signature: string
  bounds: MapBounds
  imageDataUrl: string
  boundaryPolygons?: MapPoint[][]
}

const geometryCache = new Map<string, NeutronClusterFluxGeometryCache>()

export function clearNeutronClusterFluxRasterCache(): void {
  geometryCache.clear()
}

function bodiesFromCircles(circles: readonly NeutronClusterOverlayCircle[]): StarClusterRadiationBody[] {
  return circles.map((circle) => ({
    x: circle.x,
    y: circle.y,
    radius: circle.radius,
    temp: circle.temp ?? 0,
    mass: circle.mass ?? 0,
  }))
}

function haloSearchCircles(bodies: readonly StarClusterRadiationBody[]) {
  return bodies.map((body) => ({
    x: body.x,
    y: body.y,
    radius: starClusterHaloRadiusLy(body.mass),
  }))
}

function rasterSignature(clusterName: string, bodies: readonly StarClusterRadiationBody[]): string {
  return `cell-union-v4:${clusterName}:${bodies.map((body) => `${body.x},${body.y},${body.radius},${body.temp},${body.mass}`).join('|')}`
}

function hexWithAlpha(hex: string, alpha: number): string {
  const h = hex.replace('#', '')
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function neutronClusterBoundaryStroke(bodies: readonly StarClusterRadiationBody[]): string {
  const maxTemp = bodies.reduce((max, body) => Math.max(max, body.temp), 0)
  return hexWithAlpha(neutronClusterCoreColorFromTemp(maxTemp), DISC_RIM_ALPHA)
}

function buildNeutronClusterFluxBoundaryPolygons(
  bodies: readonly StarClusterRadiationBody[],
  bounds: MapBounds
): MapPoint[][] {
  return mapCellUnionBoundaryPolylines(bodies, bounds)
}

function getOrBuildFluxGeometryCache(
  clusterName: string,
  bodies: readonly StarClusterRadiationBody[]
): NeutronClusterFluxGeometryCache | null {
  const signature = rasterSignature(clusterName, bodies)
  const cached = geometryCache.get(signature)
  if (cached != null) return cached

  const bounds = mapBoundsFromCircles(haloSearchCircles(bodies))
  if (bounds == null) return null

  const raster = rasterizeMapField(bounds, NEUTRON_CLUSTER_FLUX_MAX_RASTER_PX, (mapX, mapY) => {
    const { cellX, cellY } = mapLyToSampleCell(mapX, mapY)
    const totalFlux = starClusterRadiationSumAt(cellX, cellY, bodies)
    const alpha = Math.round(neutronClusterFluxOpacityFromTotal(totalFlux) * 255)
    if (alpha <= 0) {
      return { r: 0, g: 0, b: 0, a: 0 }
    }
    const [r, g, b] = NEUTRON_CLUSTER_FLUX_RGB
    return { r, g, b, a: alpha }
  })
  if (raster == null) return null

  const entry: NeutronClusterFluxGeometryCache = {
    signature,
    bounds,
    imageDataUrl: raster.imageDataUrl,
  }
  geometryCache.set(signature, entry)
  return entry
}

function getCachedNeutronClusterFluxBoundaryPolygons(
  clusterName: string,
  bodies: readonly StarClusterRadiationBody[]
): MapPoint[][] {
  const cache = getOrBuildFluxGeometryCache(clusterName, bodies)
  if (cache == null) return []
  if (cache.boundaryPolygons == null) {
    cache.boundaryPolygons = buildNeutronClusterFluxBoundaryPolygons(bodies, cache.bounds)
  }
  return cache.boundaryPolygons
}


export function buildNeutronClusterFluxBoundaryPaths(
  bodies: readonly StarClusterRadiationBody[],
  bounds: MapBounds,
  viewport: CartographyOverlayViewport
): string[] {
  return boundaryPathsFromMapPolygons(
    buildNeutronClusterFluxBoundaryPolygons(bodies, bounds),
    viewport
  )
}

export function buildNeutronClusterFluxPaneShapes(
  circles: readonly NeutronClusterOverlayCircle[],
  viewport: CartographyOverlayViewport,
  options?: { showOutlines?: boolean }
): NeutronClusterFluxPaneShape[] {
  const byName = new Map<string, NeutronClusterOverlayCircle[]>()
  for (const circle of circles) {
    const name = circle.name ?? 'Neutron cluster'
    const group = byName.get(name)
    if (group != null) {
      group.push(circle)
    } else {
      byName.set(name, [circle])
    }
  }

  const shapes: NeutronClusterFluxPaneShape[] = []
  const activeSignatures = new Set<string>()
  for (const [name, group] of byName) {
    const bodies = bodiesFromCircles(group)
    activeSignatures.add(rasterSignature(name, bodies))
    const geometry = getOrBuildFluxGeometryCache(name, bodies)
    if (
      geometry == null ||
      !boundsIntersectsViewport(
        geometry.bounds.minX,
        geometry.bounds.minY,
        geometry.bounds.maxX,
        geometry.bounds.maxY,
        viewport
      )
    ) {
      continue
    }

    const pane = paneRectFromBounds(geometry.bounds, viewport)
    const key = `nc-flux-${name}`
    const showOutlines = options?.showOutlines ?? false
    const boundaryPolygons = showOutlines
      ? getCachedNeutronClusterFluxBoundaryPolygons(name, bodies)
      : []
    shapes.push({
      key,
      left: pane.left,
      top: pane.top,
      width: pane.width,
      height: pane.height,
      imageDataUrl: geometry.imageDataUrl,
      fillClipPathId: `${key}-fill-clip`,
      boundaryPaths: boundaryPathsFromMapPolygons(boundaryPolygons, viewport),
      stroke: showOutlines ? neutronClusterBoundaryStroke(bodies) : '',
      strokeWidth: STAR_CLUSTER_STROKE_WIDTH,
    })
  }

  for (const signature of geometryCache.keys()) {
    if (!activeSignatures.has(signature)) {
      geometryCache.delete(signature)
    }
  }

  return shapes
}

export function neutronClusterFluxPaneShapeToRasterField(shape: NeutronClusterFluxPaneShape) {
  return {
    overlayKey: shape.key,
    left: shape.left,
    top: shape.top,
    width: shape.width,
    height: shape.height,
    imageDataUrl: shape.imageDataUrl,
    fillClipPathId: shape.fillClipPathId,
    clipPaths: shape.boundaryPaths,
    strokePaths: shape.boundaryPaths.map((path, pathIndex) => ({
      pathKey: `outer-${pathIndex}`,
      path,
      stroke: shape.stroke,
      strokeWidth: shape.strokeWidth,
    })),
  }
}
