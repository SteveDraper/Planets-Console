/**
 * Shared stream walk: visible players × active records last seen on the shell turn.
 * Rings and heading trails project separately from this enumeration (#290).
 */

import { activeFleetRecords } from './fleetRecordDisplay'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { fleetPlayerFromStreamSlice } from './fleetTablePlayerStreamState'
import type { FleetLastSeen, FleetTableRecord } from './fleetTableWireSchema'

/** Visibility DTO shared by map projectors (rings, heading trails). */
export type FleetVisiblePlayer = {
  playerId: number
  name: string
}

export type VisibleActiveOnTurnFleetRecord = {
  playerId: number
  playerName: string
  record: FleetTableRecord
  lastSeen: FleetLastSeen
}

/**
 * Yield active stream records for each visible player whose ``lastSeen.turn``
 * matches ``displayTurn``.
 */
export function* visibleActiveOnTurnFleetRecords(
  streamPlayersById: ReadonlyMap<number, FleetPlayerStreamSlice>,
  visiblePlayers: readonly FleetVisiblePlayer[],
  displayTurn: number
): Generator<VisibleActiveOnTurnFleetRecord> {
  for (const player of visiblePlayers) {
    const streamSlice = streamPlayersById.get(player.playerId)
    const merged = fleetPlayerFromStreamSlice(streamSlice, player.name)
    for (const record of activeFleetRecords(merged.records)) {
      const lastSeen = record.lastSeen
      if (lastSeen == null || lastSeen.turn !== displayTurn) {
        continue
      }
      yield {
        playerId: player.playerId,
        playerName: merged.playerName,
        record,
        lastSeen,
      }
    }
  }
}
