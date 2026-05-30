import { useQuery } from '@tanstack/react-query'
import {
  fetchStellarCartographyTurnSummary,
  type AnalyticShellScope,
} from '../../api/bff'

export function useStellarCartographyTurnSummary({
  analyticScope,
  turnDataReady,
  ionStormsGate,
}: {
  analyticScope: AnalyticShellScope | null
  turnDataReady: boolean
  ionStormsGate: boolean
}) {
  return useQuery({
    queryKey:
      analyticScope != null
        ? ([
            'concept',
            'stellar-cartography',
            'summary',
            analyticScope.gameId,
            analyticScope.turn,
            analyticScope.perspective,
          ] as const)
        : (['concept', 'stellar-cartography', 'summary', 'idle'] as const),
    queryFn: () => fetchStellarCartographyTurnSummary(analyticScope!),
    enabled: turnDataReady && analyticScope != null && ionStormsGate,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
}
