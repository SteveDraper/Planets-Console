/**
 * Resolve ownership assert keying for map/panel targets.
 * Sector-keyed when homeworld sector overlays are present; else planet-keyed.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { pointHitsMapRegionOverlayBoundary } from '../../lib/mapRegionOverlayHitTest'
import { PROVENANCE_KIND_ASSERTED } from './constants'
import { isHomeworldSectorOverlay } from './homeworldSectorIndex'
import {
  homeworldSectorsPresentOnMap,
  parseHomeworldSectorIndex,
} from './homeworldSectorIndex'

export type OwnershipAssertTarget =
  | { keying: 'sector'; sectorIndex: number; planetId?: number }
  | { keying: 'planet'; planetId: number }

/** Find the homeworld sector overlay containing map coordinates, if any. */
export function findHomeworldSectorAtMapPoint(
  overlays: readonly MapRegionOverlay[],
  mapX: number,
  mapY: number
): MapRegionOverlay | null {
  for (const overlay of overlays) {
    if (!isHomeworldSectorOverlay(overlay)) continue
    // Wedge boundary only -- envelope disks must not key ownership asserts.
    if (pointHitsMapRegionOverlayBoundary(mapX, mapY, overlay)) {
      return overlay
    }
  }
  return null
}

/**
 * Ownership target for a planet at ``(mapX, mapY)``.
 * When sectors are on the map, resolves the containing sector; otherwise planet-keyed.
 */
export function resolveOwnershipAssertTargetForPlanet(
  overlays: readonly MapRegionOverlay[],
  planetId: number,
  mapX: number,
  mapY: number
): OwnershipAssertTarget | null {
  if (!homeworldSectorsPresentOnMap(overlays)) {
    return { keying: 'planet', planetId }
  }
  const sector = findHomeworldSectorAtMapPoint(overlays, mapX, mapY)
  if (sector == null) return null
  const sectorIndex = parseHomeworldSectorIndex(sector.id)
  if (sectorIndex == null) return null
  return { keying: 'sector', sectorIndex, planetId }
}

/** Ownership target for a sector overlay context menu. */
export function resolveOwnershipAssertTargetForSector(
  overlay: MapRegionOverlay
): OwnershipAssertTarget | null {
  if (!isHomeworldSectorOverlay(overlay)) return null
  const sectorIndex = parseHomeworldSectorIndex(overlay.id)
  if (sectorIndex == null) return null
  return { keying: 'sector', sectorIndex }
}

/** Homeworld sector overlay for a parsed sector index, if present. */
export function findHomeworldSectorOverlayByIndex(
  overlays: readonly MapRegionOverlay[],
  sectorIndex: number
): MapRegionOverlay | null {
  const id = `homeworld-sector-${sectorIndex}`
  for (const overlay of overlays) {
    if (isHomeworldSectorOverlay(overlay) && overlay.id === id) {
      return overlay
    }
  }
  return null
}

/** Owner slots with user-asserted provenance on a sector overlay. */
export function collectAssertedOwnerSlots(overlay: MapRegionOverlay): number[] {
  const slots: number[] = []
  for (const owner of overlay.possibleOwners ?? []) {
    if (owner.provenanceKinds.some((kind) => kind === PROVENANCE_KIND_ASSERTED)) {
      slots.push(owner.ownerSlot)
    }
  }
  return slots
}

/**
 * Owner slots with user-asserted provenance for the ownership target.
 */
export function resolveOwnershipAssertedSlots(
  overlays: readonly MapRegionOverlay[],
  target: OwnershipAssertTarget
): number[] {
  if (target.keying !== 'sector') return []
  const overlay = findHomeworldSectorOverlayByIndex(overlays, target.sectorIndex)
  if (overlay == null) return []
  return collectAssertedOwnerSlots(overlay)
}

export type OwnershipMenuSelection = {
  /** Asserted owner slots highlighted in the roster. */
  selectedOwnerSlots: number[]
  /** Whether Unknown is the current selection (bold). */
  unknownSelected: boolean
}

/** True when the target has a single inferred owner (not asserted). */
function ownershipTargetHasInferredCurrent(
  overlays: readonly MapRegionOverlay[],
  target: OwnershipAssertTarget,
  options?: { boundOwnerSlot?: number | null }
): boolean {
  if (target.keying === 'sector') {
    const overlay = findHomeworldSectorOverlayByIndex(overlays, target.sectorIndex)
    const possibleOwners = overlay?.possibleOwners ?? []
    if (possibleOwners.length === 1) {
      return true
    }
  }
  return options?.boundOwnerSlot != null
}

/**
 * Owner submenu highlight state.
 * Roster slots are asserted owners only. Unknown is bold only when there are
 * no asserted owners and no inferred current (unique sector owner or bound slot).
 */
export function resolveOwnershipMenuSelection(
  overlays: readonly MapRegionOverlay[],
  target: OwnershipAssertTarget,
  options?: { boundOwnerSlot?: number | null }
): OwnershipMenuSelection {
  const selectedOwnerSlots = resolveOwnershipAssertedSlots(overlays, target)
  if (selectedOwnerSlots.length > 0) {
    return { selectedOwnerSlots, unknownSelected: false }
  }
  const hasInferredCurrent = ownershipTargetHasInferredCurrent(overlays, target, options)
  return {
    selectedOwnerSlots: [],
    unknownSelected: !hasInferredCurrent,
  }
}

/**
 * Owner slots to clear when picking Unknown on the map Owner submenu.
 * Planet menus mirror the panel: revoke the bound owner when known.
 * Sector menus revoke each asserted owner on the sector overlay.
 */
export function resolveOwnershipRevokeSlots(
  overlays: readonly MapRegionOverlay[],
  target: OwnershipAssertTarget,
  options?: { boundOwnerSlot?: number | null }
): number[] {
  if (options?.boundOwnerSlot != null) {
    return [options.boundOwnerSlot]
  }
  return resolveOwnershipAssertedSlots(overlays, target)
}
