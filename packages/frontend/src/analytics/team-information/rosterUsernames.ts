import type { PerspectiveRow } from '../../lib/gameInfoShell'

/** Turn-ensure usernames win over shell perspective names for the same player. */
export function rosterUsernames(
  perspectives: readonly PerspectiveRow[],
  turnUsernames: ReadonlyMap<number, string> | null
): Map<number, string> {
  const usernames = new Map<number, string>()
  for (const row of perspectives) {
    const name = row.name.trim()
    if (name) usernames.set(row.playerId, name)
  }
  if (turnUsernames != null) {
    for (const [playerId, username] of turnUsernames) {
      const trimmed = username.trim()
      if (trimmed) usernames.set(playerId, trimmed)
    }
  }
  return usernames
}
