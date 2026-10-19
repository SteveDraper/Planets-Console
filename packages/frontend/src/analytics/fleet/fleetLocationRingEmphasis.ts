/**
 * Fleet location ring emphasis: which arcs brighten, and temporary rings for
 * a visibility-off player. Temporary ships are stacked on their own so a
 * co-located rest ring keeps its diameter, opacity, stroke, and arc shares.
 */

import {
  buildFleetLocationRingStacks,
  FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE,
  type FleetLocationRingShip,
  type FleetLocationRingStack,
} from './fleetLocationRings'

/** Emphasised arcs paint fully opaque. Rest paint keeps the strength opacity. */
export const FLEET_LOCATION_RING_EMPHASIS_OPACITY = 1
/** Extra screen pixels of contrasting stroke on each side of an emphasised arc. */
export const FLEET_LOCATION_RING_EMPHASIS_OUTLINE_PX = 1

const EMPHASIS_OUTLINE_DARK = '#0b1220'
const EMPHASIS_OUTLINE_LIGHT = '#f8fafc'
/** Relative luminance above this gets a dark outline; at or below, a light one. */
const EMPHASIS_OUTLINE_LUMINANCE_SPLIT = 0.6

export type FleetLocationRingArcEmphasis = 'rest' | 'emphasis'

export function fleetLocationRingArcEmphasis(
  playerId: number,
  emphasisedPlayerIds: ReadonlySet<number>
): FleetLocationRingArcEmphasis {
  return emphasisedPlayerIds.has(playerId) ? 'emphasis' : 'rest'
}

/** Every player who owns an arc on the hovered ring. Emphasis is by player id. */
export function emphasisedPlayerIdsForRingHover(
  stack: FleetLocationRingStack
): number[] {
  return stack.arcs.map((arc) => arc.playerId)
}

export type FleetLocationRingPaintLayers = {
  restStacks: FleetLocationRingStack[]
  temporaryStacks: FleetLocationRingStack[]
}

/**
 * Rest rings from visibility-on ships, temporary rings from a visibility-off
 * player's ships. The two lists are never stacked together.
 */
export function fleetLocationRingPaintLayers(
  restShips: readonly FleetLocationRingShip[],
  temporaryShips: readonly FleetLocationRingShip[],
  strengthScale: number = FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE
): FleetLocationRingPaintLayers {
  return {
    restStacks: buildFleetLocationRingStacks(restShips, strengthScale),
    temporaryStacks: buildFleetLocationRingStacks(temporaryShips, strengthScale),
  }
}

/** Outline color that contrasts with the player-color arc stroke. */
export function fleetLocationRingEmphasisOutlineColor(strokeColor: string): string {
  const luminance = relativeLuminance(strokeColor)
  if (luminance == null || luminance <= EMPHASIS_OUTLINE_LUMINANCE_SPLIT) {
    return EMPHASIS_OUTLINE_LIGHT
  }
  return EMPHASIS_OUTLINE_DARK
}

function relativeLuminance(color: string): number | null {
  const match = /^#([0-9a-f]{6})$/i.exec(color.trim())
  if (match == null) {
    return null
  }
  const packed = Number.parseInt(match[1]!, 16)
  const red = srgbChannel((packed >> 16) & 255)
  const green = srgbChannel((packed >> 8) & 255)
  const blue = srgbChannel(packed & 255)
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue
}

function srgbChannel(byte: number): number {
  const channel = byte / 255
  if (channel <= 0.04045) {
    return channel / 12.92
  }
  return ((channel + 0.055) / 1.055) ** 2.4
}
