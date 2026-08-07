/**
 * Fleet location ring projection: stack active stream records by exact lastSeen
 * coordinates and apply AFK diameter / absolute-strength opacity + annulus (#128).
 */

import type { FleetComponentCatalog } from './fleetComponentCatalog'
import { formatFleetHullDisplay } from './fleetRecordComponentDisplay'
import { activeFleetRecords, formatFleetRecordField } from './fleetRecordDisplay'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { fleetPlayerFromStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetTableRecord } from './fleetTableWireSchema'

/** Minimum inward stroke width (px) when strength fraction is 0. */
export const FLEET_LOCATION_RING_MIN_STROKE_WIDTH_PX = 2.5
export const FLEET_LOCATION_RING_MIN_DIAMETER_PX = 8
export const FLEET_LOCATION_RING_MAX_DIAMETER_PX = 20
/** Default absolute host-mil-points scale when bootstrap / YAML omit the knob. */
export const FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE = 10_000

export type FleetLocationRingShip = {
  recordId: string
  playerId: number
  playerName: string
  shipIdLabel: string
  hullId: number | null
  hullLabel: string
  /** Host military points (militaryEstimate2x / 2), or null when not estimable. */
  hostMilitaryPoints: number | null
  x: number
  y: number
}

export type FleetLocationRingPlayerArc = {
  playerId: number
  playerName: string
  shipCount: number
  /** Fraction of stack ship count in [0, 1]. */
  share: number
  ships: readonly FleetLocationRingShip[]
}

export type FleetLocationRingStack = {
  key: string
  x: number
  y: number
  shipCount: number
  /** Sum of host mil points in the stack (E). */
  hostMilitaryPointsSum: number
  /** clamp(E / strengthScale, 0, 1). */
  strengthFraction: number
  diameterPx: number
  opacity: number
  /**
   * SVG stroke width whose outer edge stays at diameter/2 (paint at
   * radius - strokeWidth/2). Grows with strength toward a filled disk.
   */
  strokeWidthPx: number
  arcs: readonly FleetLocationRingPlayerArc[]
  ships: readonly FleetLocationRingShip[]
}

export function fleetLocationRingStackKey(x: number, y: number): string {
  return `${x},${y}`
}

/** Outer diameter in screen px: min(20, 8 + 2 * floor(log2(max(1, shipCount)))). */
export function fleetLocationRingDiameterPx(shipCount: number): number {
  const n = Math.max(1, shipCount)
  return Math.min(
    FLEET_LOCATION_RING_MAX_DIAMETER_PX,
    FLEET_LOCATION_RING_MIN_DIAMETER_PX + 2 * Math.floor(Math.log2(n))
  )
}

/**
 * Absolute strength fraction: clamp(E / strengthScale, 0, 1).
 * strengthScale is treated as at least 1.
 */
export function fleetLocationRingStrengthFraction(E: number, strengthScale: number): number {
  const denom = strengthScale >= 1 ? strengthScale : 1
  const raw = E / denom
  return Math.min(1, Math.max(0, raw))
}

/**
 * Stroke opacity from absolute strength fraction t.
 * clamp(0.40 + 0.55 * t, 0.40, 0.95).
 */
export function fleetLocationRingOpacity(strengthFraction: number): number {
  const t = Math.min(1, Math.max(0, strengthFraction))
  const raw = 0.4 + 0.55 * t
  return Math.min(0.95, Math.max(0.4, raw))
}

/**
 * Inward annulus stroke width for outer radius R and strength fraction t.
 * Weak stacks keep MIN stroke; t → 1 fills to the center (strokeWidth → R).
 */
export function fleetLocationRingStrokeWidthPx(
  diameterPx: number,
  strengthFraction: number
): number {
  const radius = diameterPx / 2
  const t = Math.min(1, Math.max(0, strengthFraction))
  const fromStrength = t * radius
  return Math.min(radius, Math.max(FLEET_LOCATION_RING_MIN_STROKE_WIDTH_PX, fromStrength))
}

/** SVG circle radius so a stroke of strokeWidthPx has its outer edge at diameter/2. */
export function fleetLocationRingPaintRadiusPx(diameterPx: number, strokeWidthPx: number): number {
  return Math.max(0, diameterPx / 2 - strokeWidthPx / 2)
}

export function hostMilitaryPointsFromEstimate2x(
  militaryEstimate2x: number | undefined
): number | null {
  if (militaryEstimate2x == null) {
    return null
  }
  return militaryEstimate2x / 2
}

export type FleetLocationRingVisiblePlayer = {
  playerId: number
  name: string
}

/** Project visibility-filtered active records last seen on the shell turn into ring ships. */
export function collectFleetLocationRingShips(
  streamPlayersById: ReadonlyMap<number, FleetPlayerStreamSlice>,
  visiblePlayers: readonly FleetLocationRingVisiblePlayer[],
  componentCatalog: FleetComponentCatalog,
  displayTurn: number
): FleetLocationRingShip[] {
  const ships: FleetLocationRingShip[] = []
  for (const player of visiblePlayers) {
    const streamSlice = streamPlayersById.get(player.playerId)
    const merged = fleetPlayerFromStreamSlice(streamSlice, player.name)
    for (const record of activeFleetRecords(merged.records)) {
      const ship = fleetLocationRingShipFromRecord(
        record,
        player.playerId,
        merged.playerName,
        componentCatalog,
        displayTurn
      )
      if (ship != null) {
        ships.push(ship)
      }
    }
  }
  return ships
}

export function fleetLocationRingShipFromRecord(
  record: FleetTableRecord,
  playerId: number,
  playerName: string,
  componentCatalog: FleetComponentCatalog,
  displayTurn: number
): FleetLocationRingShip | null {
  const lastSeen = record.lastSeen
  if (lastSeen == null || lastSeen.turn !== displayTurn) {
    return null
  }
  const hull = formatFleetHullDisplay(record, componentCatalog)
  return {
    recordId: record.recordId,
    playerId,
    playerName,
    shipIdLabel: formatFleetRecordField(record, 'shipId'),
    hullId: hull.hullId,
    hullLabel: hull.label,
    hostMilitaryPoints: hostMilitaryPointsFromEstimate2x(record.militaryEstimate2x),
    x: lastSeen.x,
    y: lastSeen.y,
  }
}

/** Stack ring ships by exact (x, y) and compute AFK paint fields for one frame. */
export function buildFleetLocationRingStacks(
  ships: readonly FleetLocationRingShip[],
  strengthScale: number = FLEET_LOCATION_RING_DEFAULT_STRENGTH_SCALE
): FleetLocationRingStack[] {
  if (ships.length === 0) {
    return []
  }

  const byKey = new Map<string, FleetLocationRingShip[]>()
  for (const ship of ships) {
    const key = fleetLocationRingStackKey(ship.x, ship.y)
    const bucket = byKey.get(key)
    if (bucket == null) {
      byKey.set(key, [ship])
    } else {
      bucket.push(ship)
    }
  }

  const stacks: FleetLocationRingStack[] = []
  for (const [key, stackShips] of byKey) {
    const hostMilitaryPointsSum = stackShips.reduce(
      (sum, ship) => sum + (ship.hostMilitaryPoints ?? 0),
      0
    )
    const strengthFraction = fleetLocationRingStrengthFraction(
      hostMilitaryPointsSum,
      strengthScale
    )
    const diameterPx = fleetLocationRingDiameterPx(stackShips.length)
    const first = stackShips[0]!
    stacks.push({
      key,
      x: first.x,
      y: first.y,
      shipCount: stackShips.length,
      hostMilitaryPointsSum,
      strengthFraction,
      diameterPx,
      opacity: fleetLocationRingOpacity(strengthFraction),
      strokeWidthPx: fleetLocationRingStrokeWidthPx(diameterPx, strengthFraction),
      arcs: buildPlayerArcs(stackShips),
      ships: stackShips,
    })
  }

  return stacks.sort((a, b) => a.key.localeCompare(b.key))
}

function buildPlayerArcs(
  stackShips: readonly FleetLocationRingShip[]
): FleetLocationRingPlayerArc[] {
  const byPlayer = new Map<number, FleetLocationRingShip[]>()
  for (const ship of stackShips) {
    const bucket = byPlayer.get(ship.playerId)
    if (bucket == null) {
      byPlayer.set(ship.playerId, [ship])
    } else {
      bucket.push(ship)
    }
  }

  const total = stackShips.length
  const playerIds = [...byPlayer.keys()].sort((a, b) => a - b)
  return playerIds.map((playerId) => {
    const ships = byPlayer.get(playerId)!
    const playerName = ships[0]!.playerName
    return {
      playerId,
      playerName,
      shipCount: ships.length,
      share: ships.length / total,
      ships,
    }
  })
}
