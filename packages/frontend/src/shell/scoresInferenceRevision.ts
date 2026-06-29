import { create } from 'zustand'
import type { AnalyticShellScope } from '../api/bff'

export function scoresInferenceScopeKey(
  scope: Pick<AnalyticShellScope, 'gameId' | 'turn' | 'perspective'>
): string {
  return `${scope.gameId}:${scope.turn}:${scope.perspective}`
}

type ScoresInferenceRevisionState = {
  revisionsByScopeKey: Record<string, number>
  bumpRevision: (scope: Pick<AnalyticShellScope, 'gameId' | 'turn' | 'perspective'>) => void
  resetRevisions: () => void
}

export const useScoresInferenceRevisionStore = create<ScoresInferenceRevisionState>()(
  (set, get) => ({
    revisionsByScopeKey: {},
    bumpRevision: (scope) => {
      const key = scoresInferenceScopeKey(scope)
      set((state) => ({
        revisionsByScopeKey: {
          ...state.revisionsByScopeKey,
          [key]: (state.revisionsByScopeKey[key] ?? 0) + 1,
        },
      }))
    },
    resetRevisions: () => {
      set({ revisionsByScopeKey: {} })
    },
  })
)

export function bumpScoresInferenceRevision(
  scope: Pick<AnalyticShellScope, 'gameId' | 'turn' | 'perspective'>
): void {
  useScoresInferenceRevisionStore.getState().bumpRevision(scope)
}

export function scoresInferenceRevisionForScope(
  scope: Pick<AnalyticShellScope, 'gameId' | 'turn' | 'perspective'>
): number {
  const key = scoresInferenceScopeKey(scope)
  return useScoresInferenceRevisionStore.getState().revisionsByScopeKey[key] ?? 0
}

export function useScoresInferenceRevision(scope: AnalyticShellScope | null): number {
  const scopeKey = scope != null ? scoresInferenceScopeKey(scope) : null
  return useScoresInferenceRevisionStore((state) =>
    scopeKey != null ? (state.revisionsByScopeKey[scopeKey] ?? 0) : 0
  )
}
