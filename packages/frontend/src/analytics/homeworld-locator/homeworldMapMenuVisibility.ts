/**
 * Pure visibility helpers for the homeworld map context menu (#37).
 */

import type { HomeworldMapMarker } from './wireSchema'

/** True when the planet wire carries a location-axis user assert. Missing marker → false. */
export function isPlanetLocationAsserted(
  markers: readonly Pick<HomeworldMapMarker, 'planetId' | 'locationAsserted'>[],
  planetId: number
): boolean {
  return markers.find((marker) => marker.planetId === planetId)?.locationAsserted === true
}

export type LocationAssertMenuActions = {
  showAssertAsHomeworld: boolean
  showRevokeHomeworldAssert: boolean
}

/** Gate Assert / Revoke HW on locationAsserted (not combined assertedCue). */
export function locationAssertMenuActions(
  locationAsserted: boolean
): LocationAssertMenuActions {
  return {
    showAssertAsHomeworld: !locationAsserted,
    showRevokeHomeworldAssert: locationAsserted,
  }
}
