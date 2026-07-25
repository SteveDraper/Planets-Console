import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import { tileClassName } from '../tileChrome'
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
  const [expanded, setExpanded] = useState(false)
  const canExpand = supportsMode && enabled
  const kinds = useVisibilityPreferencesStore((s) => s.kinds)
  const setKindEnabled = useVisibilityPreferencesStore((s) => s.setKindEnabled)
  const setKindFillColor = useVisibilityPreferencesStore((s) => s.setKindFillColor)

  useEffect(() => {
    if (!canExpand) {
      setExpanded(false)
    }
  }, [canExpand])

  const showExpandedBody = canExpand && expanded
  const chevronPointsDown = showExpandedBody

  return (
    <div
      className={cn(
        tileClassName({ supportsMode, depressed }),
        'flex min-w-0 max-w-full flex-col'
      )}
    >
      <div className="flex items-center gap-1 py-1.5 pl-2 pr-0.5">
        <label
          className={cn(
            'flex min-w-0 flex-1 cursor-pointer items-center gap-2 py-0.5',
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
        <button
          type="button"
          aria-expanded={chevronPointsDown}
          aria-label={
            chevronPointsDown ? 'Collapse Visibility layers' : 'Expand Visibility layers'
          }
          disabled={!canExpand}
          onClick={() => canExpand && setExpanded((v) => !v)}
          className={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 transition-colors',
            canExpand &&
              'hover:bg-black/15 hover:text-slate-200 focus-visible:outline focus-visible:ring-1 focus-visible:ring-slate-500',
            !canExpand && 'cursor-default opacity-40'
          )}
        >
          <ChevronDown
            className={cn(
              'h-4 w-4 shrink-0 transition-transform duration-150',
              !chevronPointsDown && '-rotate-90'
            )}
            aria-hidden
          />
        </button>
      </div>
      {showExpandedBody ? (
        <div className="flex flex-col gap-1.5 border-t border-[#52575d]/40 px-2 py-2">
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
        </div>
      ) : null}
    </div>
  )
}
