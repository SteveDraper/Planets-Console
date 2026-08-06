/**
 * Fleet location ring projection: stack active stream records by exact lastSeen
 * coordinates and apply AFK diameter / opacity / arc formulas (#128).
 */

import { colorForPlayerId } from '../../lib/playerColor'
import type { FleetComponentCatalog } from './fleetComponentCatalog'
import { formatFleetHullDisplay } from './fleetRecordComponentDisplay'
import { activeFleetRecords, formatFleetRecordField } from './fleetRecordDisplay'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { fleetPlayerFromStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetTableRecord } from './fleetTableWireSchema'

export const FLEET_LOCATION_RING_STROKE_WIDTH_PX = 2.5
export const FLEET_LOCATION_RING_MIN_DIAMETER_PX = 12
export const FLEET_LOCATION_RING_MAX_DIAMETER_PX = 20

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
  color: string
  ships: readonly FleetLocationRingShip[]
}

export type FleetLocationRingStack = {
  key: string
  x: number
  y: number
  shipCount: number
  /** Sum of host mil points in the stack (E). */
  hostMilitaryPointsSum: number
  diameterPx: number
  opacity: number
  arcs: readonly FleetLocationRingPlayerArc[]
  ships: readonly FleetLocationRingShip[]
}

export function fleetLocationRingStackKey(x: number, y: number): string {
  return `${x},${y}`
}

/** Outer diameter in screen px: min(20, 12 + 2 * floor(log2(max(1, shipCount)))). */
export function fleetLocationRingDiameterPx(shipCount: number): number {
  const n = Math.max(1, shipCount)
  return Math.min(
    FLEET_LOCATION_RING_MAX_DIAMETER_PX,
    FLEET_LOCATION_RING_MIN_DIAMETER_PX + 2 * Math.floor(Math.log2(n))
  )
}

/**
 * Stroke opacity from stack strength E vs frame max Emax.
 * clamp(0.40 + 0.55 * (E / Emax), 0.40, 0.95) with Emax treated as at least 1.
 */
export function fleetLocationRingOpacity(E: number, Emax: number): number {
  const denom = Emax > 0 ? Emax : 1
  const raw = 0.4 + 0.55 * (E / denom)
  return Math.min(0.95, Math.max(0.4, raw))
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

/** Project visibility-filtered active records with known lastSeen into ring ships. */
export function collectFleetLocationRingShips(
  streamPlayersById: ReadonlyMap<number, FleetPlayerStreamSlice>,
  visiblePlayers: readonly FleetLocationRingVisiblePlayer[],
  componentCatalog: FleetComponentCatalog
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
        componentCatalog
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
  componentCatalog: FleetComponentCatalog
): FleetLocationRingShip | null {
  const lastSeen = record.lastSeen
  if (lastSeen == null) {
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
  ships: readonly FleetLocationRingShip[]
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

  const draft: Omit<FleetLocationRingStack, 'opacity'>[] = []
  let Emax = 0
  for (const [key, stackShips] of byKey) {
    const hostMilitaryPointsSum = stackShips.reduce(
      (sum, ship) => sum + (ship.hostMilitaryPoints ?? 0),
      0
    )
    Emax = Math.max(Emax, hostMilitaryPointsSum)
    const first = stackShips[0]!
    draft.push({
      key,
      x: first.x,
      y: first.y,
      shipCount: stackShips.length,
      hostMilitaryPointsSum,
      diameterPx: fleetLocationRingDiameterPx(stackShips.length),
      arcs: buildPlayerArcs(stackShips),
      ships: stackShips,
    })
  }

  const effectiveEmax = Emax > 0 ? Emax : 1
  return draft
    .map((stack) => ({
      ...stack,
      opacity: fleetLocationRingOpacity(stack.hostMilitaryPointsSum, effectiveEmax),
    }))
    .sort((a, b) => a.key.localeCompare(b.key))
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
      color: colorForPlayerId(playerId),
      ships,
    }
  })
}
