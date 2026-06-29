import type { AnalyticShellScope } from '../api/bff'

export function analyticScopeKey(
  scope: Pick<AnalyticShellScope, 'gameId' | 'turn' | 'perspective'>
): string {
  return `${scope.gameId}:${scope.turn}:${scope.perspective}`
}
