/**
 * Fleet map projection of the shared stream. Rings and heading trails read
 * each player's map picture, not the table's later record refinements.
 */

import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'

/** Slices whose records and player name are the held map picture. */
export function fleetMapPaintSlices(
  streamPlayersById: ReadonlyMap<number, FleetPlayerStreamSlice>
): Map<number, FleetPlayerStreamSlice> {
  const painted = new Map<number, FleetPlayerStreamSlice>()
  for (const [playerId, slice] of streamPlayersById) {
    const mapPaint = slice.mapPaint
    if (mapPaint == null) {
      continue
    }
    painted.set(playerId, {
      ...slice,
      playerName: mapPaint.playerName,
      records: mapPaint.records,
    })
  }
  return painted
}
