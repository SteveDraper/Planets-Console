import { AnalyticSidebarTile } from '../AnalyticSidebarTile'
import {
  VISIBILITY_EXCLUSIONS_HELP,
  VISIBILITY_KIND_LABELS,
  VISIBILITY_REGION_KINDS,
  type VisibilityRegionKind,
} from './kinds'
import { useVisibilityPreferencesStore } from '../../stores/visibilityPreferences'

type VisibilityMapTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
}

export function VisibilityMapTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
}: VisibilityMapTileProps) {
  const kinds = useVisibilityPreferencesStore((s) => s.kinds)
  const setKindEnabled = useVisibilityPreferencesStore((s) => s.setKindEnabled)
  const setKindFillColor = useVisibilityPreferencesStore((s) => s.setKindFillColor)

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      detailsLabel="Visibility layers"
    >
      {VISIBILITY_REGION_KINDS.map((kind: VisibilityRegionKind) => {
        const pref = kinds[kind]
        return (
          <div key={kind} className="flex items-center gap-2">
            <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={pref.enabled}
                onChange={(e) => setKindEnabled(kind, e.target.checked)}
                className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
              />
              <span className="min-w-0 truncate text-xs text-slate-300">
                {VISIBILITY_KIND_LABELS[kind]}
              </span>
            </label>
            <input
              type="color"
              aria-label={`${VISIBILITY_KIND_LABELS[kind]} color`}
              value={pref.fillColor}
              onChange={(e) => setKindFillColor(kind, e.target.value)}
              className="h-6 w-7 shrink-0 cursor-pointer rounded border border-[#52575d] bg-transparent p-0"
            />
          </div>
        )
      })}
      <p className="text-[10px] leading-snug text-slate-500">{VISIBILITY_EXCLUSIONS_HELP}</p>
    </AnalyticSidebarTile>
  )
}
