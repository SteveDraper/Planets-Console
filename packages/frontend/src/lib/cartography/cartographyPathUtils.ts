import type { MapPoint } from './cartographyOverlayGeometry'

export type MapSegment = [MapPoint, MapPoint]

function mapPointKey(p: MapPoint): string {
  return `${p.x.toFixed(6)},${p.y.toFixed(6)}`
}

export function mergeNearbyMapPoints(
  segments: readonly MapSegment[],
  tolerance: number
): MapSegment[] {
  if (tolerance <= 0) return [...segments]

  const canonicalPoints: MapPoint[] = []
  const resolvePoint = (point: MapPoint): MapPoint => {
    for (const existing of canonicalPoints) {
      if (Math.hypot(existing.x - point.x, existing.y - point.y) <= tolerance) {
        return existing
      }
    }
    canonicalPoints.push(point)
    return point
  }

  return segments.map(([start, end]) => [resolvePoint(start), resolvePoint(end)])
}

/** Walk shared contour edges into continuous open or closed polylines. */
export function stitchMapSegmentsToPolylines(
  segments: readonly MapSegment[],
  mergeTolerance = 0
): MapPoint[][] {
  const mergedSegments = mergeNearbyMapPoints(segments, mergeTolerance)
  if (mergedSegments.length === 0) return []

  const canonicalByKey = new Map<string, MapPoint>()
  const canonicalPoint = (point: MapPoint): MapPoint => {
    const key = mapPointKey(point)
    const existing = canonicalByKey.get(key)
    if (existing != null) return existing
    canonicalByKey.set(key, point)
    return point
  }

  type TrackedSegment = { start: MapPoint; end: MapPoint; used: boolean }
  const tracked: TrackedSegment[] = mergedSegments.map(([start, end]) => ({
    start: canonicalPoint(start),
    end: canonicalPoint(end),
    used: false,
  }))

  const edgesAtVertex = new Map<string, number[]>()
  for (let index = 0; index < tracked.length; index += 1) {
    const segment = tracked[index]!
    for (const point of [segment.start, segment.end]) {
      const key = mapPointKey(point)
      const edgeIndexes = edgesAtVertex.get(key) ?? []
      edgeIndexes.push(index)
      edgesAtVertex.set(key, edgeIndexes)
    }
  }

  const polylines: MapPoint[][] = []

  const growChain = (chain: MapPoint[], fromHead: boolean): void => {
    while (true) {
      const tip = fromHead ? chain[0]! : chain[chain.length - 1]!
      const tipKey = mapPointKey(tip)
      const edgeIndexes = edgesAtVertex.get(tipKey) ?? []
      const nextEdgeIndex = edgeIndexes.find((index) => !tracked[index]!.used)
      if (nextEdgeIndex == null) break

      const nextEdge = tracked[nextEdgeIndex]!
      nextEdge.used = true
      const nextPoint =
        mapPointKey(nextEdge.start) === tipKey ? nextEdge.end : nextEdge.start
      if (fromHead) {
        chain.unshift(nextPoint)
      } else {
        chain.push(nextPoint)
      }
    }
  }

  for (let index = 0; index < tracked.length; index += 1) {
    const seed = tracked[index]!
    if (seed.used) continue
    seed.used = true

    const chain: MapPoint[] = [seed.start, seed.end]
    growChain(chain, false)
    growChain(chain, true)

    if (chain.length >= 2) {
      polylines.push(chain)
    }
  }

  return polylines
}
