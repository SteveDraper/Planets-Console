import type { CombinedMapData } from '../api/bff'

export const MAP_SHELL_TURN_LOADING_MESSAGE = 'Loading turn data…'
export const MAP_SHELL_MAP_LOADING_MESSAGE = 'Loading map…'

export type MapFrameSource = 'live' | 'retained' | 'none'

export type MapShellView =
  | { phase: 'full-loading'; loadingMessage: string }
  | {
      phase: 'showing-map'
      displayMapData: CombinedMapData
      showDeferredPending: boolean
    }
  | { phase: 'error'; error: unknown | null }

export type DeriveTurnEnsureLoadingInput = {
  hasAnalyticScope: boolean
  turnDataReady: boolean
  turnEnsurePending: boolean
}

export type TurnEnsureLoadingView =
  | { show: false }
  | { show: true; loadingMessage: string }

/** Shared turn-ensure loading gate for tabular and map shell paths. */
export function deriveTurnEnsureLoadingView({
  hasAnalyticScope,
  turnDataReady,
  turnEnsurePending,
}: DeriveTurnEnsureLoadingInput): TurnEnsureLoadingView {
  if (hasAnalyticScope && !turnDataReady && turnEnsurePending) {
    return { show: true, loadingMessage: MAP_SHELL_TURN_LOADING_MESSAGE }
  }
  return { show: false }
}

export type DeriveMapShellViewInput = {
  displayMapData: CombinedMapData | null
  mapFrameSource: MapFrameSource
  hasAnalyticScope: boolean
  turnDataReady: boolean
  turnEnsurePending: boolean
  mapPending: boolean
  mapHasError: boolean
  mapHasAnyData: boolean
  mapError: unknown | null
}

/** Pure retention predicates; cross-turn ref retention lives in useRetainedMapDisplay. */

export function hasDisplayableMapData(data: CombinedMapData | null | undefined): boolean {
  return (data?.nodes.length ?? 0) > 0
}

function showingMapView(
  displayMapData: CombinedMapData,
  showDeferredPending: boolean
): MapShellView {
  return {
    phase: 'showing-map',
    displayMapData,
    showDeferredPending,
  }
}

/**
 * Map-mode shell view for loading, retention, and error UI.
 *
 * Phase priority (first match wins):
 * 1. retained frame -- show prior map during turn step or refetch
 * 2. turn ensure loading -- no stored turn yet for the selected scope
 * 3. error -- fetch failed with nothing displayable
 * 4. initial map loading -- first paint or no displayable data yet
 * 5. live frame -- map visible; optional deferred pending overlay
 */
export function deriveMapShellView(input: DeriveMapShellViewInput): MapShellView {
  const {
    displayMapData,
    mapFrameSource,
    hasAnalyticScope,
    turnDataReady,
    turnEnsurePending,
    mapPending,
    mapHasError,
    mapHasAnyData,
    mapError,
  } = input

  if (mapFrameSource === 'retained' && displayMapData != null) {
    return showingMapView(displayMapData, false)
  }

  const turnEnsureLoading = deriveTurnEnsureLoadingView({
    hasAnalyticScope,
    turnDataReady,
    turnEnsurePending,
  })
  if (turnEnsureLoading.show) {
    return { phase: 'full-loading', loadingMessage: turnEnsureLoading.loadingMessage }
  }

  if (mapHasError && !mapHasAnyData) {
    return { phase: 'error', error: mapError }
  }

  if (displayMapData == null || (!mapHasAnyData && mapPending)) {
    return { phase: 'full-loading', loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE }
  }

  return showingMapView(displayMapData, mapPending && mapFrameSource === 'live')
}
