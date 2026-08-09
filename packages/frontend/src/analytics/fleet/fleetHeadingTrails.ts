/**
 * Fleet heading trail projection: rays along known wire ``motion`` from lastSeen
 * (#290). ``extendTurns`` 0 = current-turn segment only; 1..5 adds matching
 * forward and backward segments with opacity by |turnOffset|.
 */

import { headingTravelDeltaGameLy } from '../../lib/cartography/headingTravel'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetShipMotion, FleetTableRecord } from './fleetTableWireSchema'
import {
  visibleActiveOnTurnFleetRecords,
  type FleetVisiblePlayer,
} from './fleetVisibleActiveOnTurnRecords'

/** Screen-fixed stroke for heading trails (px). */
export const FLEET_HEADING_TRAIL_STROKE_WIDTH_PX = 1.5
/** Opacity for the current-turn forward segment (turnOffset 0). */
export const FLEET_HEADING_TRAIL_CURRENT_OPACITY = 0.9
/** Opacity at the farthest extended segment when ``extendTurns`` is max. */
export const FLEET_HEADING_TRAIL_MIN_OPACITY = 0.25
/** Max |turnOffset| beyond the current-turn segment (sidebar N). */
export const FLEET_HEADING_TRAIL_MAX_EXTEND_TURNS = 5

const SEGMENT_LENGTH_EPS = 1e-9

export type FleetHeadingTrail = {
  key: string
  recordId: string
  playerId: number
  /** Segment start in game map coordinates. */
  x: number
  y: number
  /** Segment end in game map coordinates. */
  endX: number
  endY: number
  heading: number
  travelLyPerTurn: number
  /**
   * Signed turn offset from the current-turn forward leg: ``0`` = current,
   * ``+k`` = further forward, ``-k`` = backward.
   */
  turnOffset: number
  opacity: number
}

/**
 * Opacity for a segment ``|turnOffset|`` steps from the current-turn leg.
 * Forward ``+k`` and backward ``-k`` share the same ramp; ``0`` is highest.
 */
export function fleetHeadingTrailOpacity(
  absTurnOffset: number,
  extendTurns: number
): number {
  const abs = Math.max(0, absTurnOffset)
  if (extendTurns <= 0 || abs <= 0) {
    return FLEET_HEADING_TRAIL_CURRENT_OPACITY
  }
  const t = Math.min(abs, extendTurns) / extendTurns
  return (
    FLEET_HEADING_TRAIL_CURRENT_OPACITY -
    t * (FLEET_HEADING_TRAIL_CURRENT_OPACITY - FLEET_HEADING_TRAIL_MIN_OPACITY)
  )
}

/** Clamp sidebar N into ``0..FLEET_HEADING_TRAIL_MAX_EXTEND_TURNS``. */
export function clampFleetHeadingTrailExtendTurns(value: number): number {
  if (!Number.isFinite(value)) {
    return 0
  }
  return Math.min(
    FLEET_HEADING_TRAIL_MAX_EXTEND_TURNS,
    Math.max(0, Math.trunc(value))
  )
}

/** Collect heading trail segments from visibility-filtered stream records. */
export function collectFleetHeadingTrails(
  streamPlayersById: ReadonlyMap<number, FleetPlayerStreamSlice>,
  visiblePlayers: readonly FleetVisiblePlayer[],
  displayTurn: number,
  extendTurns: number = 0
): FleetHeadingTrail[] {
  const turns = clampFleetHeadingTrailExtendTurns(extendTurns)
  const trails: FleetHeadingTrail[] = []
  for (const { playerId, record } of visibleActiveOnTurnFleetRecords(
    streamPlayersById,
    visiblePlayers,
    displayTurn
  )) {
    trails.push(
      ...fleetHeadingTrailSegmentsFromRecord(record, playerId, displayTurn, turns)
    )
  }
  return trails.sort((a, b) => a.key.localeCompare(b.key))
}

/** Current-turn segment only (``extendTurns = 0``). */
export function fleetHeadingTrailFromRecord(
  record: FleetTableRecord,
  playerId: number,
  displayTurn: number
): FleetHeadingTrail | null {
  const segments = fleetHeadingTrailSegmentsFromRecord(record, playerId, displayTurn, 0)
  return segments[0] ?? null
}

/**
 * Build forward (``0..extendTurns``) and backward (``-1..-extendTurns``) segments
 * for one record. Forward legs stop once a segment clamps at ``trailStop``.
 */
export function fleetHeadingTrailSegmentsFromRecord(
  record: FleetTableRecord,
  playerId: number,
  displayTurn: number,
  extendTurns: number
): FleetHeadingTrail[] {
  const lastSeen = record.lastSeen
  const motion = record.motion
  if (lastSeen == null || lastSeen.turn !== displayTurn || motion == null) {
    return []
  }
  const turns = clampFleetHeadingTrailExtendTurns(extendTurns)
  const originX = lastSeen.x
  const originY = lastSeen.y
  const { dx, dy } = headingTravelDeltaGameLy(motion.heading, motion.travelLyPerTurn)
  const segments: FleetHeadingTrail[] = []

  let cursorX = originX
  let cursorY = originY
  let stoppedForward = false
  for (let turnOffset = 0; turnOffset <= turns; turnOffset += 1) {
    if (stoppedForward) {
      break
    }
    const startX = cursorX
    const startY = cursorY
    const { endX, endY, clamped } = fleetHeadingTrailForwardEndpoint(
      startX,
      startY,
      motion,
      dx,
      dy
    )
    const length = Math.hypot(endX - startX, endY - startY)
    if (length > SEGMENT_LENGTH_EPS) {
      segments.push(
        makeTrailSegment({
          recordId: record.recordId,
          playerId,
          x: startX,
          y: startY,
          endX,
          endY,
          heading: motion.heading,
          travelLyPerTurn: motion.travelLyPerTurn,
          turnOffset,
          opacity: fleetHeadingTrailOpacity(turnOffset, turns),
        })
      )
    }
    if (clamped) {
      stoppedForward = true
    } else {
      cursorX = endX
      cursorY = endY
    }
  }

  for (let k = 1; k <= turns; k += 1) {
    const endX = originX - (k - 1) * dx
    const endY = originY - (k - 1) * dy
    const startX = originX - k * dx
    const startY = originY - k * dy
    const length = Math.hypot(endX - startX, endY - startY)
    if (length <= SEGMENT_LENGTH_EPS) {
      continue
    }
    segments.push(
      makeTrailSegment({
        recordId: record.recordId,
        playerId,
        x: startX,
        y: startY,
        endX,
        endY,
        heading: motion.heading,
        travelLyPerTurn: motion.travelLyPerTurn,
        turnOffset: -k,
        opacity: fleetHeadingTrailOpacity(k, turns),
      })
    )
  }

  return segments
}

/**
 * One-turn endpoint along heading at ``travelLyPerTurn``, clamped to ``trailStop``
 * when that stop is within the one-turn travel distance from the segment start.
 */
export function fleetHeadingTrailEndpoint(
  originX: number,
  originY: number,
  motion: FleetShipMotion
): { x: number; y: number } {
  const { dx, dy } = headingTravelDeltaGameLy(motion.heading, motion.travelLyPerTurn)
  const { endX, endY } = fleetHeadingTrailForwardEndpoint(
    originX,
    originY,
    motion,
    dx,
    dy
  )
  return { x: endX, y: endY }
}

function fleetHeadingTrailForwardEndpoint(
  startX: number,
  startY: number,
  motion: FleetShipMotion,
  dx: number,
  dy: number
): { endX: number; endY: number; clamped: boolean } {
  const uncappedX = startX + dx
  const uncappedY = startY + dy
  const stop = motion.trailStop
  const stopDistance = Math.hypot(stop.x - startX, stop.y - startY)
  if (stopDistance <= motion.travelLyPerTurn + SEGMENT_LENGTH_EPS) {
    return { endX: stop.x, endY: stop.y, clamped: true }
  }
  return { endX: uncappedX, endY: uncappedY, clamped: false }
}

function makeTrailSegment(
  fields: Omit<FleetHeadingTrail, 'key'>
): FleetHeadingTrail {
  return {
    ...fields,
    key: `${fields.recordId}:t${fields.turnOffset}:${fields.x},${fields.y}`,
  }
}
