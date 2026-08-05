/**
 * Subscribe to the map-shell base-map query for planet id → coordinates.
 * Uses ``defaultMapAnalyticQuerySpec`` so key and queryFn match
 * ``useMapAnalyticQueries`` / ``mapAnalyticQuerySpecFor`` for base-map
 * (single semantic owner; TanStack dedupes observers).
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { BASE_MAP_ANALYTIC_ID } from '../mapAnalyticIds'
import { defaultMapAnalyticQuerySpec } from '../mapAnalyticRegistry'
import { planetPositionsFromBaseMap } from './planetPositionsFromBaseMap'

const EMPTY_POSITIONS: ReadonlyMap<number, { x: number; y: number }> = new Map()

export type UseBaseMapPlanetPositionsOptions = {
  analyticScope: AnalyticShellScope | null
  /** When false, do not fetch or wait on base-map positions. */
  fetchEnabled: boolean
}

export function useBaseMapPlanetPositions({
  analyticScope,
  fetchEnabled,
}: UseBaseMapPlanetPositionsOptions) {
  const query = useQuery(
    defaultMapAnalyticQuerySpec(BASE_MAP_ANALYTIC_ID, analyticScope, fetchEnabled)
  )

  const planetPositions = useMemo(() => {
    if (!query.isSuccess) return EMPTY_POSITIONS
    return planetPositionsFromBaseMap(query.data?.nodes ?? [])
  }, [query.isSuccess, query.data?.nodes])

  return {
    planetPositions,
    positionsReady: query.isSuccess,
    positionsError: query.error ?? null,
  }
}
