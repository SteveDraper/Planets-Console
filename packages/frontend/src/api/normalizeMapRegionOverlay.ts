/**
 * Normalize map region overlay wire JSON (syntactic parsing before UI merge).
 */

import type {
  MapRegionBoundaryArcEdge,
  MapRegionBoundaryEdge,
  MapRegionBoundaryGeometry,
  MapRegionBoundaryLineEdge,
  MapRegionCoverageGeometry,
  MapRegionCoverageRleRun,
  MapRegionOverlay,
  MapRegionOverlayDisk,
  MapRegionOverlayGeometry,
  MapRegionOverlayPatch,
  MapRegionOverlayVertex,
  MapRegionPossibleOwner,
} from './mapRegionOverlayTypes'
import { parseJsonFiniteNumber, parseJsonInteger } from './normalizeMapWireParsing'

function normalizeCoverageRleRun(raw: unknown): MapRegionCoverageRleRun | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const length = parseJsonInteger(o.length)
  if (length == null || length < 0) return null
  if (typeof o.covered !== 'boolean') return null
  return { length, covered: o.covered }
}

function normalizeDisk(raw: unknown): MapRegionOverlayDisk | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const x = parseJsonFiniteNumber(o.x)
  const y = parseJsonFiniteNumber(o.y)
  const radius = parseJsonFiniteNumber(o.radius)
  if (x == null || y == null || radius == null || radius < 0) return null
  return { x, y, radius }
}

function normalizePatch(raw: unknown): MapRegionOverlayPatch | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const originX = parseJsonInteger(o.originX ?? o.origin_x)
  const originY = parseJsonInteger(o.originY ?? o.origin_y)
  const width = parseJsonInteger(o.width)
  const height = parseJsonInteger(o.height)
  if (originX == null || originY == null || width == null || height == null) return null
  if (width <= 0 || height <= 0) return null
  const rleRaw = o.coverageRle ?? o.coverage_rle
  if (!Array.isArray(rleRaw)) return null
  const coverageRle = rleRaw
    .map(normalizeCoverageRleRun)
    .filter((run): run is MapRegionCoverageRleRun => run != null)
  const expected = width * height
  const total = coverageRle.reduce((sum, run) => sum + run.length, 0)
  if (total !== expected) return null
  return { originX, originY, width, height, coverageRle }
}

function normalizeVertex(raw: unknown): MapRegionOverlayVertex | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const x = parseJsonFiniteNumber(o.x)
  const y = parseJsonFiniteNumber(o.y)
  if (x == null || y == null) return null
  return { x, y }
}

function normalizeBoundaryEdge(raw: unknown): MapRegionBoundaryEdge | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const type = typeof o.type === 'string' ? o.type : null
  if (type === 'line') {
    const edge: MapRegionBoundaryLineEdge = { type: 'line' }
    return edge
  }
  if (type === 'arc') {
    const centerX = parseJsonFiniteNumber(o.centerX ?? o.center_x)
    const centerY = parseJsonFiniteNumber(o.centerY ?? o.center_y)
    if (centerX == null || centerY == null) return null
    if (typeof o.clockwise !== 'boolean') return null
    const edge: MapRegionBoundaryArcEdge = {
      type: 'arc',
      centerX,
      centerY,
      clockwise: o.clockwise,
    }
    return edge
  }
  return null
}

function normalizeDisks(raw: unknown): MapRegionOverlayDisk[] | null {
  if (!Array.isArray(raw)) return null
  const disks: MapRegionOverlayDisk[] = []
  for (const item of raw) {
    const disk = normalizeDisk(item)
    if (disk == null) return null
    disks.push(disk)
  }
  return disks
}

function normalizePatches(raw: unknown): MapRegionOverlayPatch[] | null {
  if (!Array.isArray(raw)) return null
  const patches: MapRegionOverlayPatch[] = []
  for (const item of raw) {
    const patch = normalizePatch(item)
    if (patch == null) return null
    patches.push(patch)
  }
  return patches
}

function normalizeCoverageGeometry(raw: Record<string, unknown>): MapRegionCoverageGeometry | null {
  const disks = normalizeDisks(raw.disks)
  const patches = normalizePatches(raw.patches)
  if (disks == null || patches == null) return null
  return { type: 'coverage', disks, patches }
}

function normalizeBoundaryGeometry(raw: Record<string, unknown>): MapRegionBoundaryGeometry | null {
  const verticesRaw = raw.vertices
  const edgesRaw = raw.edges
  if (!Array.isArray(verticesRaw) || !Array.isArray(edgesRaw)) return null
  if (edgesRaw.length !== verticesRaw.length) return null

  // Disks-only boundary: empty path carries envelope disks (no outline).
  if (verticesRaw.length === 0) {
    const disks = normalizeDisks(raw.disks)
    if (disks == null || disks.length === 0) return null
    return { type: 'boundary', vertices: [], edges: [], disks }
  }

  if (verticesRaw.length < 3) return null

  const vertices: MapRegionOverlayVertex[] = []
  for (const item of verticesRaw) {
    const vertex = normalizeVertex(item)
    if (vertex == null) return null
    vertices.push(vertex)
  }
  const edges: MapRegionBoundaryEdge[] = []
  for (const item of edgesRaw) {
    const edge = normalizeBoundaryEdge(item)
    if (edge == null) return null
    edges.push(edge)
  }

  const geometry: MapRegionBoundaryGeometry = { type: 'boundary', vertices, edges }
  if (raw.disks !== undefined) {
    const disks = normalizeDisks(raw.disks)
    if (disks == null) return null
    if (disks.length > 0) geometry.disks = disks
  }
  return geometry
}

function normalizeGeometry(raw: unknown): MapRegionOverlayGeometry | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const type = typeof o.type === 'string' ? o.type : null
  if (type === 'coverage') return normalizeCoverageGeometry(o)
  if (type === 'boundary') return normalizeBoundaryGeometry(o)
  return null
}

/**
 * Legacy flat disks+patches without a geometry discriminant parse as coverage
 * so older fixtures and in-flight payloads still normalize.
 */
function normalizeLegacyCoverage(raw: Record<string, unknown>): MapRegionOverlayGeometry | null {
  if (!Array.isArray(raw.disks) || !Array.isArray(raw.patches)) return null
  return normalizeCoverageGeometry(raw)
}

function normalizeOptionalBoolean(raw: unknown): boolean | undefined {
  if (raw === undefined) return undefined
  if (typeof raw !== 'boolean') return undefined
  return raw
}

function normalizeOptionalString(raw: unknown): string | undefined {
  if (raw === undefined) return undefined
  if (typeof raw !== 'string' || raw === '') return undefined
  return raw
}

function normalizeOptionalNonNegativeInt(raw: unknown): number | undefined {
  if (raw === undefined) return undefined
  const n = parseJsonInteger(raw)
  if (n == null || n < 0) return undefined
  return n
}

export function normalizeMapRegionOverlay(raw: unknown): MapRegionOverlay | null {
  if (raw == null || typeof raw !== 'object') return null
  const o = raw as Record<string, unknown>
  const kind = typeof o.kind === 'string' ? o.kind : null
  const id = typeof o.id === 'string' ? o.id : null
  if (kind == null || id == null || kind === '' || id === '') return null
  const fillColor =
    typeof o.fillColor === 'string'
      ? o.fillColor
      : typeof o.fill_color === 'string'
        ? o.fill_color
        : null
  const fillOpacity = parseJsonFiniteNumber(o.fillOpacity ?? o.fill_opacity)
  if (fillColor == null || fillOpacity == null) return null
  if (fillOpacity < 0 || fillOpacity > 1) return null

  let geometry: MapRegionOverlayGeometry | null = null
  if (o.geometry !== undefined) {
    geometry = normalizeGeometry(o.geometry)
  } else {
    geometry = normalizeLegacyCoverage(o)
  }
  if (geometry == null) return null

  const overlay: MapRegionOverlay = { kind, id, fillColor, fillOpacity, geometry }
  const isPinned = normalizeOptionalBoolean(o.isPinned ?? o.is_pinned)
  if (isPinned !== undefined) overlay.isPinned = isPinned
  // Reject non-boolean isPinned when the key is present
  if ((o.isPinned !== undefined || o.is_pinned !== undefined) && isPinned === undefined) {
    return null
  }
  const status = normalizeOptionalString(o.status)
  if (o.status !== undefined && status === undefined) return null
  if (status !== undefined) overlay.status = status
  const candidateCount = normalizeOptionalNonNegativeInt(
    o.candidateCount ?? o.candidate_count
  )
  if (
    (o.candidateCount !== undefined || o.candidate_count !== undefined) &&
    candidateCount === undefined
  ) {
    return null
  }
  if (candidateCount !== undefined) overlay.candidateCount = candidateCount
  const playerLabel = normalizeOptionalString(o.playerLabel ?? o.player_label)
  if (
    (o.playerLabel !== undefined || o.player_label !== undefined) &&
    playerLabel === undefined
  ) {
    return null
  }
  if (playerLabel !== undefined) overlay.playerLabel = playerLabel
  const possibleOwners = normalizePossibleOwners(o.possibleOwners ?? o.possible_owners)
  if (
    (o.possibleOwners !== undefined || o.possible_owners !== undefined) &&
    possibleOwners === undefined
  ) {
    return null
  }
  if (possibleOwners !== undefined) overlay.possibleOwners = possibleOwners
  const winningStrength = normalizeOptionalString(
    o.ownershipWinningStrength ?? o.ownership_winning_strength
  )
  if (
    (o.ownershipWinningStrength !== undefined ||
      o.ownership_winning_strength !== undefined) &&
    winningStrength === undefined
  ) {
    return null
  }
  if (winningStrength !== undefined) {
    if (
      winningStrength !== 'weak' &&
      winningStrength !== 'strong' &&
      winningStrength !== 'asserted'
    ) {
      return null
    }
    overlay.ownershipWinningStrength = winningStrength
  }
  return overlay
}

function normalizeProvenanceKindCounts(
  raw: unknown
): Record<string, number> | undefined {
  if (raw === undefined) return undefined
  if (raw == null || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const counts: Record<string, number> = {}
  for (const [kind, value] of Object.entries(raw as Record<string, unknown>)) {
    if (kind === '') return undefined
    const count = parseJsonInteger(value)
    if (count == null || count < 0) return undefined
    counts[kind] = count
  }
  return counts
}

function normalizePossibleOwners(raw: unknown): MapRegionPossibleOwner[] | undefined {
  if (raw === undefined) return undefined
  if (!Array.isArray(raw)) return undefined
  const owners: MapRegionPossibleOwner[] = []
  for (const entry of raw) {
    if (entry == null || typeof entry !== 'object') return undefined
    const row = entry as Record<string, unknown>
    const ownerSlot = parseJsonInteger(row.ownerSlot ?? row.owner_slot)
    if (ownerSlot == null || ownerSlot < 1) return undefined
    const kindsRaw = row.provenanceKinds ?? row.provenance_kinds
    if (!Array.isArray(kindsRaw)) return undefined
    const provenanceKinds: string[] = []
    for (const kind of kindsRaw) {
      if (typeof kind !== 'string' || kind === '') return undefined
      provenanceKinds.push(kind)
    }
    const owner: MapRegionPossibleOwner = { ownerSlot, provenanceKinds }
    const label = normalizeOptionalString(row.playerLabel ?? row.player_label)
    if (
      (row.playerLabel !== undefined || row.player_label !== undefined) &&
      label === undefined
    ) {
      return undefined
    }
    if (label !== undefined) owner.playerLabel = label
    const counts = normalizeProvenanceKindCounts(
      row.provenanceKindCounts ?? row.provenance_kind_counts
    )
    if (
      (row.provenanceKindCounts !== undefined ||
        row.provenance_kind_counts !== undefined) &&
      counts === undefined
    ) {
      return undefined
    }
    if (counts !== undefined) owner.provenanceKindCounts = counts
    owners.push(owner)
  }
  return owners
}

export function normalizeMapRegionOverlays(raw: unknown): MapRegionOverlay[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map(normalizeMapRegionOverlay)
    .filter((o): o is MapRegionOverlay => o != null)
}
