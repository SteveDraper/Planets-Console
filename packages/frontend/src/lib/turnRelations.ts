/** Minimal turn Relation fields needed for diplomacy-family player color. */
export type TurnRelationEdge = {
  playerid: number
  playertoid: number
  relationfrom: number
  relationto: number
}

function readFiniteInt(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null
  }
  return Math.trunc(value)
}

/** Parse ``relations`` from a turn ensure / TurnInfo JSON payload. */
export function turnRelationsFromPayload(data: unknown): TurnRelationEdge[] {
  if (data == null || typeof data !== 'object') {
    return []
  }
  const record = data as Record<string, unknown>
  const raw = record.relations
  if (!Array.isArray(raw)) {
    return []
  }
  const edges: TurnRelationEdge[] = []
  for (const entry of raw) {
    if (entry == null || typeof entry !== 'object') {
      continue
    }
    const row = entry as Record<string, unknown>
    const playerid = readFiniteInt(row.playerid)
    const playertoid = readFiniteInt(row.playertoid)
    const relationfrom = readFiniteInt(row.relationfrom)
    const relationto = readFiniteInt(row.relationto)
    if (
      playerid == null ||
      playertoid == null ||
      relationfrom == null ||
      relationto == null
    ) {
      continue
    }
    edges.push({ playerid, playertoid, relationfrom, relationto })
  }
  return edges
}

/**
 * Inbound grants to ``viewpointPlayerId``: other player id → ``relationfrom``.
 * Only rows where ``playerid === viewpoint``; self rows skipped.
 */
export function inboundRelationFromByPlayerId(
  relations: readonly TurnRelationEdge[],
  viewpointPlayerId: number
): Map<number, number> {
  const map = new Map<number, number>()
  for (const edge of relations) {
    if (edge.playerid !== viewpointPlayerId) {
      continue
    }
    if (edge.playertoid === viewpointPlayerId) {
      continue
    }
    map.set(edge.playertoid, edge.relationfrom)
  }
  return map
}
