import { useCallback, useEffect, useState } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { pauseInferenceGlobally, resumeInferenceGlobally } from '../../api/bff'
import { errorDetailFromUnknown } from '../../lib/queryRetry'

export type UseGlobalInferencePauseResult = {
  isGloballyPaused: boolean
  isPending: boolean
  error: string | null
  pauseGlobally: () => Promise<void>
  resumeGlobally: () => Promise<void>
  syncPausedFromStream: (paused: boolean) => void
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

  const syncPausedFromStream = useCallback((paused: boolean) => {
    setIsGloballyPaused(paused)
  }, [])

  return {
    isGloballyPaused,
    isPending,
    error,
    pauseGlobally,
    resumeGlobally,
    syncPausedFromStream,
  }
}
