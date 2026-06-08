import { useCallback, useEffect, useState } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import {
  fetchInferenceGlobalPauseStatus,
  pauseInferenceGlobally,
  resumeInferenceGlobally,
} from '../../api/bff'
import { errorDetailFromUnknown } from '../../lib/queryRetry'

export type UseGlobalInferencePauseResult = {
  isGloballyPaused: boolean
  isPending: boolean
  error: string | null
  pauseGlobally: () => Promise<void>
  resumeGlobally: () => Promise<void>
}

export function useGlobalInferencePause(
  scope: AnalyticShellScope | null,
  enabled: boolean
): UseGlobalInferencePauseResult {
  const [isGloballyPaused, setIsGloballyPaused] = useState(false)
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!enabled || scope == null) {
      setIsGloballyPaused(false)
      setError(null)
      return
    }

    let cancelled = false
    void fetchInferenceGlobalPauseStatus(scope)
      .then((status) => {
        if (!cancelled) {
          setIsGloballyPaused(status.paused)
          setError(null)
        }
      })
      .catch((fetchError) => {
        if (!cancelled) {
          setError(errorDetailFromUnknown(fetchError))
        }
      })

    return () => {
      cancelled = true
    }
  }, [enabled, scope?.gameId, scope?.turn, scope?.perspective])

  const pauseGlobally = useCallback(async () => {
    if (scope == null) {
      return
    }
    setIsPending(true)
    setError(null)
    try {
      const status = await pauseInferenceGlobally(scope)
      setIsGloballyPaused(status.paused)
    } catch (pauseError) {
      setError(errorDetailFromUnknown(pauseError))
    } finally {
      setIsPending(false)
    }
  }, [scope])

  const resumeGlobally = useCallback(async () => {
    if (scope == null) {
      return
    }
    setIsPending(true)
    setError(null)
    try {
      const status = await resumeInferenceGlobally(scope)
      setIsGloballyPaused(status.paused)
    } catch (resumeError) {
      setError(errorDetailFromUnknown(resumeError))
    } finally {
      setIsPending(false)
    }
  }, [scope])

  return {
    isGloballyPaused,
    isPending,
    error,
    pauseGlobally,
    resumeGlobally,
  }
}
