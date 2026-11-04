import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { fetchHomeworldFleetAgeRefetch } from './api'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from './constants'
import { homeworldLocatorMapQueryKey } from './mapAnalytic'

/** Poll while the locator is enabled. The map query's own fetch checks stamps. */
export const HOMEWORLD_FLEET_AGE_REFETCH_INTERVAL_MS = 2000

export type FleetAgeRefetchSession = {
  watching: true
}

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

export function useHomeworldFleetAgeRefetch(
  analyticScope: AnalyticShellScope | null,
  enabled: boolean
): FleetAgeRefetchSession {
  const queryClient = useQueryClient()
  const afterEpochRef = useRef(0)
  const hasSampledRef = useRef(false)
  const scopeKey =
    analyticScope == null ? '' : `${analyticScope.gameId}:${analyticScope.perspective}`
  useEffect(() => {
    afterEpochRef.current = 0
    hasSampledRef.current = false
  }, [scopeKey])

  useQuery({
    queryKey: [
      'analytic',
      HOMEWORLD_LOCATOR_ANALYTIC_ID,
      'fleet-age-refetch',
      analyticScope?.gameId ?? null,
      analyticScope?.perspective ?? null,
    ],
    enabled: enabled && analyticScope != null,
    refetchInterval: HOMEWORLD_FLEET_AGE_REFETCH_INTERVAL_MS,
    queryFn: async () => {
      if (analyticScope == null) {
        throw new Error('fleet-age refetch requires a shell scope')
      }
      const notice = await fetchHomeworldFleetAgeRefetch(
        analyticScope,
        afterEpochRef.current
      )
      const refetch = shownShellRefetchesForFleetAgeNotice({
        hasSampled: hasSampledRef.current,
        shellTurn: analyticScope.turn,
        fromTurn: notice.fromTurn,
      })
      hasSampledRef.current = true
      afterEpochRef.current = notice.epoch
      if (refetch) {
        await queryClient.invalidateQueries({
          queryKey: homeworldLocatorMapQueryKey(analyticScope),
        })
      }
      return notice
    },
  })

  return { watching: true }
}
