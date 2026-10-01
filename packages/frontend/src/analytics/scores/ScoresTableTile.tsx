import { cn } from '../../lib/utils'
import { AnalyticSidebarTile } from '../AnalyticSidebarTile'
import type { AnalyticShellScope } from '../../api/bff'
import { usePersistStoreHydrated } from '../../lib/usePersistStoreHydrated'
import { useScoresTablePreferencesStore } from '../../stores/scoresTablePreferences'
import { useBuildInferenceAvailable } from './useBuildInferenceAvailable'

type ScoresTableTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  turnDataReady: boolean
  analyticScope: AnalyticShellScope | null
}

export function ScoresTableTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  turnDataReady,
  analyticScope,
}: ScoresTableTileProps) {
  const scoresTableParams = useScoresTablePreferencesStore((s) => s.scoresTableParams)
  const setScoresTableParams = useScoresTablePreferencesStore((s) => s.setScoresTableParams)
  const scoresPreferencesHydrated = usePersistStoreHydrated(useScoresTablePreferencesStore)
  const buildInferenceAvailable = useBuildInferenceAvailable(
    analyticScope,
    scoresTableParams,
    supportsMode && enabled && turnDataReady && scoresPreferencesHydrated
  )
  const inferenceControlEnabled = buildInferenceAvailable === true
  const stealthUnavailable = buildInferenceAvailable === false

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      detailsLabel="Scores options"
    >
      <label
        className={cn(
          'flex items-center gap-2',
          inferenceControlEnabled ? 'cursor-pointer' : 'cursor-default text-slate-500'
        )}
        title={
          stealthUnavailable
            ? 'Stealth Mode hides military scores; build inference is unavailable'
            : undefined
        }
      >
        <input
          type="checkbox"
          checked={scoresTableParams.includeBuildInference}
          disabled={!inferenceControlEnabled}
          title={
            stealthUnavailable
              ? 'Stealth Mode hides military scores; build inference is unavailable'
              : undefined
          }
          onChange={(e) =>
            setScoresTableParams({
              ...scoresTableParams,
              includeBuildInference: e.target.checked,
            })
          }
          className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 accent-slate-400 disabled:opacity-50"
        />
        <span>Include build inference</span>
      </label>
    </AnalyticSidebarTile>
  )
}
