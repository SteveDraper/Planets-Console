import { formatViewpointRowLabel } from '../../lib/displayFormatters'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'
import { fleetPlayerFromStreamSlice } from './fleetTablePlayerStreamState'

export function fleetPlayerDisplayLabel(
  player: Pick<PerspectiveRow, 'playerId' | 'name' | 'raceName'>,
  racePlayerLabels: Map<number, string>,
  streamSlice: FleetPlayerStreamSlice | undefined
): string {
  const fromScores = racePlayerLabels.get(player.playerId)
  if (fromScores != null) {
    return fromScores
  }
  const merged = fleetPlayerFromStreamSlice(streamSlice, player.name)
  return formatViewpointRowLabel('player_and_race_names', merged.playerName, player.raceName)
}
