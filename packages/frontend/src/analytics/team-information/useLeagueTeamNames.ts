import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchLeagueTeams } from '../../api/bff'

export function leagueTeamsQueryKey(gameId: string) {
  return ['bff', 'games', gameId, 'league-teams'] as const
}

/**
 * Directory names for the open game.
 * Not part of the team-information map query, so territory compute does not wait on it.
 */
export function useLeagueTeamNames(
  gameId: string | null,
  enabled: boolean
): ReadonlyMap<number, string | null> {
  const queryEnabled = enabled && gameId != null && gameId !== ''
  const { data } = useQuery({
    queryKey: leagueTeamsQueryKey(gameId ?? ''),
    queryFn: () => {
      if (gameId == null || gameId === '') {
        throw new Error('League teams query requires a game id')
      }
      return fetchLeagueTeams(gameId)
    },
    enabled: queryEnabled,
  })

  return useMemo(() => {
    const names = new Map<number, string | null>()
    for (const team of data?.teams ?? []) {
      names.set(team.id, team.name)
    }
    return names
  }, [data])
}
