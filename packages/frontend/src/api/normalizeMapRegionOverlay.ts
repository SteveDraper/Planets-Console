/**
 * Normalize map region overlay wire JSON (syntactic parsing before UI merge).
 */

import type {
  MapRegionCoverageRleRun,
  MapRegionOverlay,
  MapRegionOverlayDisk,
  MapRegionOverlayPatch,
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
  const disksRaw = o.disks
  const patchesRaw = o.patches
  if (!Array.isArray(disksRaw) || !Array.isArray(patchesRaw)) return null
  const disks: MapRegionOverlayDisk[] = []
  for (const raw of disksRaw) {
    const disk = normalizeDisk(raw)
    if (disk == null) return null
    disks.push(disk)
  }
  const patches: MapRegionOverlayPatch[] = []
  for (const raw of patchesRaw) {
    const patch = normalizePatch(raw)
    if (patch == null) return null
    patches.push(patch)
  }
  return { kind, id, fillColor, fillOpacity, disks, patches }
}

export function normalizeMapRegionOverlays(raw: unknown): MapRegionOverlay[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map(normalizeMapRegionOverlay)
    .filter((o): o is MapRegionOverlay => o != null)
}
