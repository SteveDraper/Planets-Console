import { useQuery } from '@tanstack/react-query'
import { fetchViewpointEligibility } from '../api/bff'
import { useSessionStore } from '../stores/session'
import { useShellStore } from '../stores/shell'

export function viewpointEligibilityQueryKey(gameId: string, loginTrimmed: string) {
  return ['bff', 'games', gameId, 'viewpoint-eligibility', loginTrimmed] as const
}

/** BFF allowed perspective slots for the current login; null while loading or when login is empty. */
export function useEligiblePerspectives(): number[] | null {
  const loginName = useSessionStore((s) => s.name)
  const selectedGameId = useShellStore((s) => s.selectedGameId)
  const loginTrimmed = loginName?.trim() ?? ''
  const eligibilityEnabled = Boolean(selectedGameId) && loginTrimmed !== ''
  const { data: eligibility } = useQuery({
    queryKey: viewpointEligibilityQueryKey(selectedGameId ?? '', loginTrimmed),
    queryFn: () => fetchViewpointEligibility(selectedGameId!, loginTrimmed),
    enabled: eligibilityEnabled,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  if (!eligibilityEnabled) {
    return null
  }
  return eligibility?.perspectives ?? null
}
