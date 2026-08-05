/**
 * Subscribe to the homeworld-locator map-layer query for sector overlays.
 * Uses ``homeworldLocatorMapQuerySpec`` so key and queryFn match
 * ``useMapAnalyticQueries`` / homeworld map registration
 * (single semantic owner; TanStack dedupes observers).
 *
 * Same pattern as ``useBaseMapPlanetPositions`` for base-map coordinates.
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { homeworldLocatorMapQuerySpec } from './mapAnalytic'

const EMPTY_OVERLAYS: readonly MapRegionOverlay[] = []

export type UseHomeworldLocatorMapOverlaysOptions = {
  analyticScope: AnalyticShellScope | null
  /** When false, do not fetch or wait on homeworld map overlays. */
  fetchEnabled: boolean
}

export function useHomeworldLocatorMapOverlays({
  analyticScope,
  fetchEnabled,
}: UseHomeworldLocatorMapOverlaysOptions) {
  const query = useQuery(homeworldLocatorMapQuerySpec(analyticScope, fetchEnabled))

  const overlays = useMemo(
    () => query.data?.regionOverlays ?? EMPTY_OVERLAYS,
    [query.data?.regionOverlays]
  )

  return {
    overlays,
    overlaysReady: fetchEnabled && query.isSuccess,
    overlaysError: query.error ?? null,
  }
}
