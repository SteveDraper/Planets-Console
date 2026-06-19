import { useCallback, useState } from 'react'
import { RotateCcw } from 'lucide-react'
import type { AnalyticShellScope } from '../../api/bff'
import { fetchScoresInferenceRecompute } from '../../api/bff'

type InferenceRecomputeControlProps = {
  scope: AnalyticShellScope
}

export function InferenceRecomputeControl({ scope }: InferenceRecomputeControlProps) {
  const [isPending, setIsPending] = useState(false)

  const recompute = useCallback(async () => {
    setIsPending(true)
    try {
      await fetchScoresInferenceRecompute(scope)
    } catch {
      // Stream events carry row state; failed recompute leaves current rows as-is.
    } finally {
      setIsPending(false)
    }
  }, [scope])

  return (
    <button
      type="button"
      title="Recompute all build inference for this turn"
      aria-label="Recompute all build inference for this turn"
      disabled={isPending}
      onClick={() => void recompute()}
      className="inline-flex items-center justify-center rounded p-0.5 text-slate-300 hover:bg-white/10 hover:text-slate-100 disabled:opacity-50"
    >
      <RotateCcw className="h-3.5 w-3.5" aria-hidden />
    </button>
  )
}
