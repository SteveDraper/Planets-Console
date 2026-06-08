import { Pause, Play } from 'lucide-react'
import type { UseGlobalInferencePauseResult } from './useGlobalInferencePause'

type GlobalInferencePauseControlProps = {
  globalInferencePause: UseGlobalInferencePauseResult
}

export function GlobalInferencePauseControl({
  globalInferencePause,
}: GlobalInferencePauseControlProps) {
  const { isGloballyPaused, isPending, pauseGlobally, resumeGlobally } = globalInferencePause

  if (isGloballyPaused) {
    return (
      <button
        type="button"
        title="Resume all build inference for this turn"
        aria-label="Resume all build inference for this turn"
        disabled={isPending}
        onClick={() => void resumeGlobally()}
        className="inline-flex items-center justify-center rounded p-0.5 text-slate-300 hover:bg-white/10 hover:text-slate-100 disabled:opacity-50"
      >
        <Play className="h-3.5 w-3.5 fill-current" aria-hidden />
      </button>
    )
  }

  return (
    <button
      type="button"
      title="Pause all build inference for this turn"
      aria-label="Pause all build inference for this turn"
      disabled={isPending}
      onClick={() => void pauseGlobally()}
      className="inline-flex items-center justify-center rounded p-0.5 text-slate-300 hover:bg-white/10 hover:text-slate-100 disabled:opacity-50"
    >
      <Pause className="h-3.5 w-3.5 fill-current" aria-hidden />
    </button>
  )
}
