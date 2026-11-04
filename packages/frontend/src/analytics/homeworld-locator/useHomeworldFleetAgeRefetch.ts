import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import {
  fetchHomeworldFleetAgeRefetch,
  type FleetAgeRefetchNotice,
} from './api'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from './constants'
import { homeworldLocatorMapQueryKey } from './mapAnalytic'

/** Poll while the locator is enabled. The map query's own fetch checks stamps. */
export const HOMEWORLD_FLEET_AGE_REFETCH_INTERVAL_MS = 2000

/**
 * Shown shell refetches when a later sample reports a change at or before that shell.
 * The first sample only records the epoch.
 */
export function shownShellRefetchesForFleetAgeNotice(input: {
  hasSampled: boolean
  shellTurn: number
  fromTurn: number | null | undefined
}): boolean {
  if (!input.hasSampled) return false
  if (input.fromTurn == null) return false
  return input.shellTurn >= input.fromTurn
}

export type FleetAgeRefetchSample = {
  epoch: number
}

/**
 * `previous` is missing for the first poll of a cache entry. Game and perspective
 * are the cache key, so a change of either starts again from a missing sample.
 */
export function nextFleetAgeRefetchSample(
  previous: FleetAgeRefetchSample | undefined,
  notice: FleetAgeRefetchNotice,
  shellTurn: number,
): { sample: FleetAgeRefetchSample; shouldRefetch: boolean } {
  return {
    sample: { epoch: notice.epoch },
    shouldRefetch: shownShellRefetchesForFleetAgeNotice({
      hasSampled: previous != null,
      shellTurn,
      fromTurn: notice.fromTurn,
    }),
  }
}

type FleetAgeRefetchPoll = {
  sample: FleetAgeRefetchSample
  shouldRefetch: boolean
  scope: AnalyticShellScope
}

/** Shown turn stays out of the key so a turn change keeps the baseline sample. */
export function homeworldFleetAgeRefetchQueryKey(
  scope: Pick<AnalyticShellScope, 'gameId' | 'perspective'> | null,
) {
  return [
    'analytic',
    HOMEWORLD_LOCATOR_ANALYTIC_ID,
    'fleet-age-refetch',
    scope?.gameId ?? null,
    scope?.perspective ?? null,
  ] as const
}

export function useHomeworldFleetAgeRefetch(
  analyticScope: AnalyticShellScope | null,
  enabled: boolean,
): undefined {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: homeworldFleetAgeRefetchQueryKey(analyticScope),
    enabled: enabled && analyticScope != null,
    refetchInterval: HOMEWORLD_FLEET_AGE_REFETCH_INTERVAL_MS,
    queryFn: async ({ client, queryKey }) => {
      if (analyticScope == null) {
        throw new Error('fleet-age refetch requires a shell scope')
      }
      const previous = client.getQueryData<FleetAgeRefetchPoll>(queryKey)
      const notice = await fetchHomeworldFleetAgeRefetch(
        analyticScope,
        previous?.sample.epoch ?? 0,
      )
      const step = nextFleetAgeRefetchSample(
        previous?.sample,
        notice,
        analyticScope.turn,
      )
      return { ...step, scope: analyticScope }
    },
  })

  const poll = query.data
  useEffect(() => {
    if (poll == null || !poll.shouldRefetch) return
    void queryClient.invalidateQueries({
      queryKey: homeworldLocatorMapQueryKey(poll.scope),
    })
  }, [poll, queryClient])
}
