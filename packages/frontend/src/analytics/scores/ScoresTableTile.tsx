import { cn } from '../../lib/utils'
import { tileClassName } from '../tileChrome'
import type { ScoresTableParams } from './api'

type ScoresTableTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  scoresTableParams: ScoresTableParams
  onScoresTableParamsChange: (next: ScoresTableParams) => void
  buildInferenceAvailable?: boolean
}

export function ScoresTableTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  scoresTableParams,
  onScoresTableParamsChange,
  buildInferenceAvailable = true,
}: ScoresTableTileProps) {
  const showInferenceOption = supportsMode && enabled

  return (
    <div
      className={cn(
        tileClassName({ supportsMode, depressed }),
        'flex min-w-0 max-w-full flex-col'
      )}
    >
      <label
        className={cn(
          'flex cursor-pointer items-center gap-2 px-2 py-1.5',
          !supportsMode && 'cursor-default'
        )}
      >
        <input
          type="checkbox"
          checked={enabled}
          onChange={() => supportsMode && onToggle()}
          disabled={!supportsMode}
          className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
        />
        <span className="min-w-0 truncate">{name}</span>
      </label>
      {showInferenceOption ? (
        <label
          className={cn(
            'flex items-center gap-2 border-t border-[#52575d]/70 px-2 py-1.5 pl-8 text-xs text-slate-300',
            buildInferenceAvailable ? 'cursor-pointer' : 'cursor-default text-slate-500'
          )}
          title={
            buildInferenceAvailable
              ? undefined
              : 'Stealth Mode hides military scores; build inference is unavailable'
          }
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="checkbox"
            checked={scoresTableParams.includeBuildInference}
            disabled={!buildInferenceAvailable}
            title={
              buildInferenceAvailable
                ? undefined
                : 'Stealth Mode hides military scores; build inference is unavailable'
            }
            onChange={(e) =>
              onScoresTableParamsChange({
                ...scoresTableParams,
                includeBuildInference: e.target.checked,
              })
            }
            className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 accent-slate-400 disabled:opacity-50"
          />
          <span>Include build inference</span>
        </label>
      ) : null}
    </div>
  )
}
