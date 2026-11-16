import { useEffect } from 'react'
import type { AnalyticShellScope } from '../api/bff'
import { fetchComputeDiagnosticsFreezeStatus } from '../api/bffComputeDiagnostics'
import { analyticScopeKey } from './analyticScopeKey'
import { useComputeDiagnosticsStore } from '../stores/computeDiagnostics'

/**
 * When compute diagnostics are enabled, keep freezeStatus in sync with the server
 * for the current shell. Independent of the Compute-tab heavy snapshot.
 *
 * The fetch also notifies the server of the shell, so freeze scopes to it on a
 * turn or perspective change even when no table stream opens.
 */
export function useComputeFreezeStatusSync(scope: AnalyticShellScope | null): void {
  const enabled = useComputeDiagnosticsStore((state) => state.enabled)
  const setFreezeStatus = useComputeDiagnosticsStore((state) => state.setFreezeStatus)
  const scopeKey = scope != null ? analyticScopeKey(scope) : null

  useEffect(() => {
    if (!enabled || scope == null || scopeKey == null) {
      setFreezeStatus(null)
      return
    }

    let cancelled = false
    void fetchComputeDiagnosticsFreezeStatus(scope)
      .then((status) => {
        if (cancelled) {
          return
        }
        setFreezeStatus(status)
      })
      .catch(() => {
        if (cancelled) {
          return
        }
        setFreezeStatus(null)
      })

    return () => {
      cancelled = true
    }
  }, [enabled, scope, scopeKey, setFreezeStatus])
}
