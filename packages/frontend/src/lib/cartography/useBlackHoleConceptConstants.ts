import { useQuery } from '@tanstack/react-query'
import { fetchBlackHoleConceptConstants, type BlackHoleConceptConstants } from '../../api/bff'

export function useBlackHoleConceptConstants(): BlackHoleConceptConstants | undefined {
  const { data } = useQuery({
    queryKey: ['bff', 'concepts', 'stellar-cartography', 'black-holes'] as const,
    queryFn: fetchBlackHoleConceptConstants,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  })
  return data
}
