/**
 * Pure model helpers for the homeworld locator sector accordion panel:
 * northernmost-then-clockwise sector order, preferred-first candidates,
 * sector titles, and planet→sector grouping.
 */

import type {
  MapRegionBoundaryGeometry,
  MapRegionOverlay,
} from '../../api/mapRegionOverlayTypes'
import { CONFIDENCE_DEFINITE } from './constants'
import { formatHomeworldSectorHoverLine } from './formatHomeworldSectorHover'
import { findHomeworldSectorAtMapPoint } from './resolveOwnershipAssertTarget'
import {
  homeworldSectorsPresentOnMap,
  isHomeworldSectorOverlay,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'
import type { HomeworldCandidateRecord } from './wireSchema'

export type HomeworldSectorPanelSection = {
  sectorIndex: number
  overlay: MapRegionOverlay
  title: string
  titleHover: string | null
  candidates: readonly HomeworldCandidateRecord[]
}

export type HomeworldSectorPanelModel =
  | {
      kind: 'sectors'
      sections: readonly HomeworldSectorPanelSection[]
      unassigned: readonly HomeworldCandidateRecord[]
    }
  | {
      kind: 'flat'
      candidates: readonly HomeworldCandidateRecord[]
    }

/** Map-center from the first arc edge on a homeworld sector boundary. */
export function mapCenterFromSectorBoundary(
  geometry: MapRegionBoundaryGeometry
): { x: number; y: number } | null {
  for (const edge of geometry.edges) {
    if (edge.type === 'arc') {
      return { x: edge.centerX, y: edge.centerY }
    }
  }
  return null
}

/**
 * Mid-angle of a sector wedge (radians, map Y-up atan2).
 * Prefers outer-arc endpoints (Core emission: vertices[0]=start, vertices[1]=end);
 * falls back to circular mean of vertices about the arc center or vertex centroid.
 */
export function sectorMidAngleRadians(overlay: MapRegionOverlay): number | null {
  if (overlay.geometry.type !== 'boundary') return null
  const geometry = overlay.geometry
  const verts = geometry.vertices
  if (verts.length < 2) return null

  const center = mapCenterFromSectorBoundary(geometry) ?? vertexCentroid(verts)
  if (center == null) return null

  const hasOuterArc =
    geometry.edges.length >= 1 && geometry.edges[0]?.type === 'arc'
  if (hasOuterArc) {
    const start = verts[0]!
    const end = verts[1]!
    const angleStart = Math.atan2(start.y - center.y, start.x - center.x)
    const angleEnd = Math.atan2(end.y - center.y, end.x - center.x)
    let span = angleEnd - angleStart
    if (span <= 0) span += 2 * Math.PI
    return angleStart + 0.5 * span
  }

  // Line-only boundaries (tests / degenerate): mean of unit vectors from center.
  let sumX = 0
  let sumY = 0
  for (const vertex of verts) {
    const dx = vertex.x - center.x
    const dy = vertex.y - center.y
    const len = Math.hypot(dx, dy)
    if (len < 1e-9) continue
    sumX += dx / len
    sumY += dy / len
  }
  if (sumX === 0 && sumY === 0) return null
  return Math.atan2(sumY, sumX)
}

function vertexCentroid(
  vertices: readonly { x: number; y: number }[]
): { x: number; y: number } | null {
  if (vertices.length === 0) return null
  let sx = 0
  let sy = 0
  for (const vertex of vertices) {
    sx += vertex.x
    sy += vertex.y
  }
  return { x: sx / vertices.length, y: sy / vertices.length }
}

/**
 * Clockwise-from-north sort key: 0 at +Y (north), increasing clockwise.
 * Northernmost sectors sort first.
 */
export function clockwiseFromNorthSortKey(midAngleRadians: number): number {
  const twoPi = 2 * Math.PI
  return (((Math.PI / 2 - midAngleRadians) % twoPi) + twoPi) % twoPi
}

/** Sort homeworld sector overlays northernmost-first, then clockwise. */
export function sortHomeworldSectorsNorthernmostClockwise(
  overlays: readonly MapRegionOverlay[]
): MapRegionOverlay[] {
  const sectors = overlays.filter(isHomeworldSectorOverlay)
  return [...sectors].sort((a, b) => {
    const angleA = sectorMidAngleRadians(a)
    const angleB = sectorMidAngleRadians(b)
    if (angleA == null && angleB == null) {
      return (parseHomeworldSectorIndex(a.id) ?? 0) - (parseHomeworldSectorIndex(b.id) ?? 0)
    }
    if (angleA == null) return 1
    if (angleB == null) return -1
    const keyDiff = clockwiseFromNorthSortKey(angleA) - clockwiseFromNorthSortKey(angleB)
    if (keyDiff !== 0) return keyDiff
    return (parseHomeworldSectorIndex(a.id) ?? 0) - (parseHomeworldSectorIndex(b.id) ?? 0)
  })
}

/**
 * Sector accordion title: unique projected owner label, else Unknown.
 * Does not prefer pinned ``playerLabel`` over multi-member ownership evidence
 * (that mismatch was claiming a unique owner while hover said ambiguous).
 * When ownership evidence is empty, fall back to pinned player identity.
 */
export function homeworldSectorAccordionTitle(overlay: MapRegionOverlay): string {
  const possibleOwners = overlay.possibleOwners ?? []
  if (possibleOwners.length === 1) {
    const owner = possibleOwners[0]!
    if (owner.playerLabel != null && owner.playerLabel !== '') {
      return owner.playerLabel
    }
    return `Slot ${owner.ownerSlot}`
  }
  if (possibleOwners.length > 1) {
    return 'Unknown'
  }
  if (overlay.playerLabel != null && overlay.playerLabel !== '') {
    return overlay.playerLabel
  }
  return 'Unknown'
}

/** Preferred-first: definite → most probable → remaining possibles; stable by planetId. */
export function sortCandidatesPreferredFirst(
  rows: readonly HomeworldCandidateRecord[]
): HomeworldCandidateRecord[] {
  return [...rows].sort((a, b) => {
    const rankDiff = preferredCandidateRank(a) - preferredCandidateRank(b)
    if (rankDiff !== 0) return rankDiff
    return a.planetId - b.planetId
  })
}

function preferredCandidateRank(row: HomeworldCandidateRecord): number {
  if (row.confidenceTier === CONFIDENCE_DEFINITE) return 0
  if (row.isMostProbable) return 1
  return 2
}

/**
 * Build accordion model: per-sector sections when homeworld-sector overlays exist,
 * otherwise a flat candidate list (non-circular / no-overlay games).
 */
export function buildHomeworldSectorPanelModel(
  rows: readonly HomeworldCandidateRecord[],
  overlays: readonly MapRegionOverlay[],
  planetPositions: ReadonlyMap<number, { x: number; y: number }>
): HomeworldSectorPanelModel {
  if (!homeworldSectorsPresentOnMap(overlays)) {
    return { kind: 'flat', candidates: sortCandidatesPreferredFirst(rows) }
  }

  const orderedSectors = sortHomeworldSectorsNorthernmostClockwise(overlays)
  const bySector = new Map<number, HomeworldCandidateRecord[]>()
  for (const overlay of orderedSectors) {
    const index = parseHomeworldSectorIndex(overlay.id)
    if (index != null) bySector.set(index, [])
  }

  const unassigned: HomeworldCandidateRecord[] = []
  for (const row of rows) {
    const pos = planetPositions.get(row.planetId)
    if (pos == null) {
      unassigned.push(row)
      continue
    }
    const sector = findHomeworldSectorAtMapPoint(overlays, pos.x, pos.y)
    if (sector == null) {
      unassigned.push(row)
      continue
    }
    const index = parseHomeworldSectorIndex(sector.id)
    if (index == null) {
      unassigned.push(row)
      continue
    }
    const bucket = bySector.get(index)
    if (bucket == null) {
      unassigned.push(row)
      continue
    }
    bucket.push(row)
  }

  const sections: HomeworldSectorPanelSection[] = orderedSectors.flatMap((overlay) => {
    const sectorIndex = parseHomeworldSectorIndex(overlay.id)
    if (sectorIndex == null) return []
    return [
      {
        sectorIndex,
        overlay,
        title: homeworldSectorAccordionTitle(overlay),
        titleHover: formatHomeworldSectorHoverLine(overlay),
        candidates: sortCandidatesPreferredFirst(bySector.get(sectorIndex) ?? []),
      },
    ]
  })

  return {
    kind: 'sectors',
    sections,
    unassigned: sortCandidatesPreferredFirst(unassigned),
  }
}
