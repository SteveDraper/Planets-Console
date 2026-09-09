/**
 * Hit-test and hover copy for known minefields (pre-decay disk).
 */

import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { minefieldTypeId, type MinefieldTypeId } from './types'
import type { KnownMinefield } from './wireSchema'

export function knownMinefieldsAtPoint(
  fields: readonly KnownMinefield[],
  mapX: number,
  mapY: number,
  enabledTypes: ReadonlySet<MinefieldTypeId>
): KnownMinefield[] {
  const hits = fields.filter((field) => {
    if (!enabledTypes.has(minefieldTypeId(field.isWeb))) return false
    const dist = Math.hypot(mapX - field.x, mapY - field.y)
    return dist <= field.preRadius
  })
  hits.sort((a, b) => a.preRadius - b.preRadius || a.id - b.id)
  return hits
}

export function ownerNameForMinefield(
  ownerId: number,
  roster: readonly PerspectiveRow[]
): string {
  const row = roster.find((p) => p.playerId === ownerId)
  return row?.name ?? `Player ${ownerId}`
}

export function formatMinefieldHoverLines(
  fields: readonly KnownMinefield[],
  roster: readonly PerspectiveRow[],
  shellTurn: number
): string[] {
  return fields.map((field) => {
    const typeLabel = field.isWeb ? 'web' : 'normal'
    const owner = ownerNameForMinefield(field.ownerId, roster)
    const stale = field.infoTurn < shellTurn
    const turnLabel = stale ? `turn ${field.infoTurn} (stale)` : `turn ${field.infoTurn}`
    const parts = [
      typeLabel,
      owner,
      `${field.units} units`,
      `pre ${field.preRadius} / post ${field.postRadius}`,
      turnLabel,
    ]
    if (field.friendlyCode.length > 0) {
      parts.push(field.friendlyCode)
    }
    return parts.join(' · ')
  })
}
