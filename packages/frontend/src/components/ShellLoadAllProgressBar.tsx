import { useEffect, useState } from 'react'
import type { LoadAllProgressUpdate } from '../api/bff'
import { cn } from '../lib/utils'

type ShellLoadAllProgressBarProps = {
  progress: LoadAllProgressUpdate
}

const ELLIPSIS_FRAMES = ['.', '..', '...'] as const
const ELLIPSIS_INTERVAL_MS = 400

function progressPercent(current: number, total: number): number {
  if (total <= 0) {
    return 0
  }
  return Math.min(100, Math.round((current / total) * 100))
}

function LoadTrack({ value, label }: { value: number; label: string }) {
  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      aria-label={label}
      className="h-2 w-full overflow-hidden rounded-full bg-slate-800/90"
    >
      <div
        className={cn('h-full rounded-full bg-sky-500/90 transition-[width] duration-150')}
        style={{ width: `${value}%` }}
      />
    </div>
  )
}

function AnimatedPhaseMessage({ message }: { message: string }) {
  const [frameIndex, setFrameIndex] = useState(0)

  useEffect(() => {
    const id = window.setInterval(() => {
      setFrameIndex((current) => (current + 1) % ELLIPSIS_FRAMES.length)
    }, ELLIPSIS_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [])

  return (
    <p className="mt-2 text-xs leading-snug text-slate-500">
      {message}
      <span aria-hidden className="inline-block min-w-[1.25em] tabular-nums">
        {ELLIPSIS_FRAMES[frameIndex]}
      </span>
    </p>
  )
}

export function ShellLoadAllProgressBar({ progress }: ShellLoadAllProgressBarProps) {
  const showTurnProgress = progress.phase !== 'final_turn'
  const perspectivePercent = progressPercent(progress.perspective, progress.perspective_total)
  const turnPercent = progressPercent(progress.turn, progress.turn_total)
  const perspectiveLabel =
    progress.perspective_total > 0
      ? `${progress.perspective} / ${progress.perspective_total}`
      : progress.phase === 'download'
        ? '…'
        : '—'
  const turnLabel =
    progress.turn_total > 0 ? `${progress.turn} / ${progress.turn_total}` : '—'

  return (
    <div
      role="status"
      aria-live="polite"
      className="w-full shrink-0 border-b border-slate-800 bg-[#151a22] px-3 py-2.5"
    >
      <div
        className={cn(
          'flex w-full flex-col gap-2',
          showTurnProgress ? 'sm:flex-row sm:gap-6' : null
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center justify-between gap-2 text-xs text-slate-400">
            <span>Perspectives</span>
            <span className="tabular-nums">{perspectiveLabel}</span>
          </div>
          <LoadTrack value={perspectivePercent} label="Perspective progress" />
        </div>
        {showTurnProgress ? (
          <div className="min-w-0 flex-1">
            <div className="mb-1 flex items-center justify-between gap-2 text-xs text-slate-400">
              <span>Turns</span>
              <span className="tabular-nums">{turnLabel}</span>
            </div>
            <LoadTrack value={turnPercent} label="Turn progress within perspective" />
          </div>
        ) : null}
      </div>
      {progress.message ? <AnimatedPhaseMessage message={progress.message} /> : null}
    </div>
  )
}
