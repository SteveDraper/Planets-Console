/**
 * Fleet heading trail projection: one current-turn ray per active stream record
 * with known wire ``motion`` and lastSeen on the shell turn (#290).
 */

import { headingTravelDeltaGameLy } from '../../lib/cartography/ionStormMovement'
import { activeFleetRecords } from './fleetRecordDisplay'
import type { FleetLocationRingVisiblePlayer } from './fleetLocationRings'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { fleetPlayerFromStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetShipMotion, FleetTableRecord } from './fleetTableWireSchema'

/** Screen-fixed stroke for current-turn heading trails (px). */
export const FLEET_HEADING_TRAIL_STROKE_WIDTH_PX = 1.5
/** Opacity for the current-turn (nearest) segment. */
export const FLEET_HEADING_TRAIL_CURRENT_OPACITY = 0.9

export type FleetHeadingTrail = {
  key: string
  recordId: string
  playerId: number
  /** Origin map cell (lastSeen), same as location-ring stack. */
  x: number
  y: number
  /** One-turn endpoint in game map coordinates. */
  endX: number
  endY: number
  heading: number
  travelLyPerTurn: number
  opacity: number
}

/** Collect current-turn heading trails from visibility-filtered stream records. */
export function collectFleetHeadingTrails(
  streamPlayersById: ReadonlyMap<number, FleetPlayerStreamSlice>,
  visiblePlayers: readonly FleetLocationRingVisiblePlayer[],
  displayTurn: number
): FleetHeadingTrail[] {
  const trails: FleetHeadingTrail[] = []
  for (const player of visiblePlayers) {
    const streamSlice = streamPlayersById.get(player.playerId)
    const merged = fleetPlayerFromStreamSlice(streamSlice, player.name)
    for (const record of activeFleetRecords(merged.records)) {
      const trail = fleetHeadingTrailFromRecord(record, player.playerId, displayTurn)
      if (trail != null) {
        trails.push(trail)
      }
    }
  }
  return trails.sort((a, b) => a.key.localeCompare(b.key))
}

export function fleetHeadingTrailFromRecord(
  record: FleetTableRecord,
  playerId: number,
  displayTurn: number
): FleetHeadingTrail | null {
  const lastSeen = record.lastSeen
  const motion = record.motion
  if (lastSeen == null || lastSeen.turn !== displayTurn || motion == null) {
    return null
  }
  const endpoint = fleetHeadingTrailEndpoint(lastSeen.x, lastSeen.y, motion)
  return {
    key: `${record.recordId}:${lastSeen.x},${lastSeen.y}`,
    recordId: record.recordId,
    playerId,
    x: lastSeen.x,
    y: lastSeen.y,
    endX: endpoint.x,
    endY: endpoint.y,
    heading: motion.heading,
    travelLyPerTurn: motion.travelLyPerTurn,
    opacity: FLEET_HEADING_TRAIL_CURRENT_OPACITY,
  }
}

/**
 * One-turn endpoint along heading at ``travelLyPerTurn``, clamped to ``trailStop``
 * when that stop is within the one-turn travel distance.
 */
export function fleetHeadingTrailEndpoint(
  originX: number,
  originY: number,
  motion: FleetShipMotion
): { x: number; y: number } {
  const { dx, dy } = headingTravelDeltaGameLy(motion.heading, motion.travelLyPerTurn)
  const uncapped = { x: originX + dx, y: originY + dy }
  const stop = motion.trailStop
  if (stop == null) {
    return uncapped
  }
  const stopDistance = Math.hypot(stop.x - originX, stop.y - originY)
  if (stopDistance <= motion.travelLyPerTurn + 1e-9) {
    return { x: stop.x, y: stop.y }
  }
  return uncapped
}
