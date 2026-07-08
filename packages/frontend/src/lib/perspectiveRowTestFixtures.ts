import type { PerspectiveRow } from './gameInfoShell'

type PerspectiveRowFixtureOptions = {
  playerId?: number
  raceName?: string | null
  eliminationTurn?: number | null
}

/** Build a `PerspectiveRow` for tests; `playerId` defaults to `ordinal`. */
export function perspectiveRow(
  ordinal: number,
  name: string,
  options: PerspectiveRowFixtureOptions = {}
): PerspectiveRow {
  return {
    ordinal,
    playerId: options.playerId ?? ordinal,
    name,
    raceName: options.raceName ?? null,
    eliminationTurn: options.eliminationTurn ?? null,
  }
}
