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
  | { phase: 'error' }

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
}

/** Pure retention predicates; cross-turn ref retention lives in useRetainedMapDisplay. */

export function hasDisplayableMapData(data: CombinedMapData | null | undefined): boolean {
  return (data?.nodes.length ?? 0) > 0
}

/** Map-mode shell view for loading, retention, and error UI. */
export function deriveMapShellView({
  displayMapData,
  mapFrameSource,
  hasAnalyticScope,
  turnDataReady,
  turnEnsurePending,
  mapPending,
  mapHasError,
  mapHasAnyData,
}: DeriveMapShellViewInput): MapShellView {
  if (mapFrameSource === 'retained' && displayMapData != null) {
    return {
      phase: 'showing-map',
      displayMapData,
      showDeferredPending: false,
    }
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
    return { phase: 'error' }
  }

  if (displayMapData == null || (!mapHasAnyData && mapPending)) {
    return { phase: 'full-loading', loadingMessage: MAP_SHELL_MAP_LOADING_MESSAGE }
  }

  return {
    phase: 'showing-map',
    displayMapData,
    showDeferredPending: mapPending && mapFrameSource === 'live',
  }
}
