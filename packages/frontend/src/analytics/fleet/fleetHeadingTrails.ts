/**
 * Fleet heading trail projection: rays along known wire ``motion`` from lastSeen
 * (#290). ``extendTurns`` 0 = current-turn segment only; 1..5 adds matching
 * forward and backward segments with opacity by |turnOffset|.
 *
 * Ordinary (non-HYP) rays also clamp on exact planet hit or when a one-turn
 * endpoint lands in a planet cell / server ``normalWellCells``. Back-trails are
 * omitted when the origin is already on a planet / in a well.
 */

import { headingTravelDeltaGameLy } from '../../lib/cartography/headingTravel'
import {
  firstFleetTrailPlanetStopAlongSegment,
  pointInAnyFleetTrailPlanetStop,
  type FleetTrailPlanetStop,
} from './fleetHeadingTrailPlanetStops'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetShipMotion, FleetTableRecord } from './fleetTableWireSchema'
import {
  visibleActiveOnTurnFleetRecords,
  type FleetVisiblePlayer,
} from './fleetVisibleActiveOnTurnRecords'

/** Screen-fixed stroke for heading trails (px). */
export const FLEET_HEADING_TRAIL_STROKE_WIDTH_PX = 1.5
/** SVG dash pattern for hyperjump (HYP) current-turn trails. */
export const FLEET_HEADING_TRAIL_HYPERJUMP_DASHARRAY = '5 4'
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
  /** True when this segment is a performing hyperjump (dotted current-turn only). */
  isHyperjump: boolean
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
  extendTurns: number = 0,
  planets: readonly FleetTrailPlanetStop[] = []
): FleetHeadingTrail[] {
  const turns = clampFleetHeadingTrailExtendTurns(extendTurns)
  const trails: FleetHeadingTrail[] = []
  for (const { playerId, record } of visibleActiveOnTurnFleetRecords(
    streamPlayersById,
    visiblePlayers,
    displayTurn
  )) {
    trails.push(
      ...fleetHeadingTrailSegmentsFromRecord(
        record,
        playerId,
        displayTurn,
        turns,
        planets
      )
    )
  }
  return trails.sort((a, b) => a.key.localeCompare(b.key))
}

/** Current-turn segment only (``extendTurns = 0``). */
export function fleetHeadingTrailFromRecord(
  record: FleetTableRecord,
  playerId: number,
  displayTurn: number,
  planets: readonly FleetTrailPlanetStop[] = []
): FleetHeadingTrail | null {
  const segments = fleetHeadingTrailSegmentsFromRecord(
    record,
    playerId,
    displayTurn,
    0,
    planets
  )
  return segments[0] ?? null
}

/**
 * Build forward (``0..extendTurns``) and backward (``-1..-extendTurns``) segments
 * for one record. Forward legs stop at ``trailStop`` or the first planet/well
 * stop (exact planet on the segment, or end-of-turn in a well). Backward legs
 * use the same rule (and are omitted entirely when the origin is already on a
 * planet / in a well). Performing hyperjumps always emit only the current-turn
 * segment and skip planet/well path clamps.
 */
export function fleetHeadingTrailSegmentsFromRecord(
  record: FleetTableRecord,
  playerId: number,
  displayTurn: number,
  extendTurns: number,
  planets: readonly FleetTrailPlanetStop[] = []
): FleetHeadingTrail[] {
  const lastSeen = record.lastSeen
  const motion = record.motion
  if (lastSeen == null || lastSeen.turn !== displayTurn || motion == null) {
    return []
  }
  const isHyperjump = motion.hyperjump === true
  const turns = isHyperjump ? 0 : clampFleetHeadingTrailExtendTurns(extendTurns)
  const pathPlanets = isHyperjump ? [] : planets
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
      dy,
      pathPlanets
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
          isHyperjump,
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

  if (
    turns > 0 &&
    !pointInAnyFleetTrailPlanetStop(originX, originY, pathPlanets)
  ) {
    let nearX = originX
    let nearY = originY
    for (let k = 1; k <= turns; k += 1) {
      const proposedFarX = nearX - dx
      const proposedFarY = nearY - dy
      const planetHit = firstFleetTrailPlanetStopAlongSegment(
        nearX,
        nearY,
        proposedFarX,
        proposedFarY,
        pathPlanets,
        { skipPlanetsContainingStart: true }
      )
      let farX = proposedFarX
      let farY = proposedFarY
      let stopFurther = false
      if (planetHit != null) {
        farX = planetHit.x
        farY = planetHit.y
        stopFurther = true
      }
      const length = Math.hypot(nearX - farX, nearY - farY)
      if (length > SEGMENT_LENGTH_EPS) {
        segments.push(
          makeTrailSegment({
            recordId: record.recordId,
            playerId,
            x: farX,
            y: farY,
            endX: nearX,
            endY: nearY,
            heading: motion.heading,
            travelLyPerTurn: motion.travelLyPerTurn,
            turnOffset: -k,
            opacity: fleetHeadingTrailOpacity(k, turns),
            isHyperjump: false,
          })
        )
      }
      if (stopFurther) {
        break
      }
      nearX = proposedFarX
      nearY = proposedFarY
    }
  }

  return segments
}

/**
 * One-turn endpoint along heading at ``travelLyPerTurn``, clamped to ``trailStop``
 * or a planet/well stop (exact planet on the segment, or end-of-turn in a well)
 * when that stop is within the one-turn travel distance from the segment start.
 */
export function fleetHeadingTrailEndpoint(
  originX: number,
  originY: number,
  motion: FleetShipMotion,
  planets: readonly FleetTrailPlanetStop[] = []
): { x: number; y: number } {
  const { dx, dy } = headingTravelDeltaGameLy(motion.heading, motion.travelLyPerTurn)
  const { endX, endY } = fleetHeadingTrailForwardEndpoint(
    originX,
    originY,
    motion,
    dx,
    dy,
    motion.hyperjump === true ? [] : planets
  )
  return { x: endX, y: endY }
}

function fleetHeadingTrailForwardEndpoint(
  startX: number,
  startY: number,
  motion: FleetShipMotion,
  dx: number,
  dy: number,
  planets: readonly FleetTrailPlanetStop[]
): { endX: number; endY: number; clamped: boolean } {
  const uncappedX = startX + dx
  const uncappedY = startY + dy

  type Candidate = { x: number; y: number; distance: number }
  const candidates: Candidate[] = []

  const stop = motion.trailStop
  const trailStopDistance = Math.hypot(stop.x - startX, stop.y - startY)
  if (trailStopDistance <= motion.travelLyPerTurn + SEGMENT_LENGTH_EPS) {
    candidates.push({ x: stop.x, y: stop.y, distance: trailStopDistance })
  }

  const planetHit = firstFleetTrailPlanetStopAlongSegment(
    startX,
    startY,
    uncappedX,
    uncappedY,
    planets,
    { skipPlanetsContainingStart: true }
  )
  if (planetHit != null) {
    candidates.push({
      x: planetHit.x,
      y: planetHit.y,
      distance: Math.hypot(planetHit.x - startX, planetHit.y - startY),
    })
  }

  if (candidates.length > 0) {
    candidates.sort((a, b) => a.distance - b.distance)
    const nearest = candidates[0]!
    return { endX: nearest.x, endY: nearest.y, clamped: true }
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
