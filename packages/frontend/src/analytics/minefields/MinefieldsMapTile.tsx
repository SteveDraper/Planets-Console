import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import { tileClassName } from '../tileChrome'
import { DisplayModeControl } from '../DisplayModeControl'
import { useMinefieldsPreferencesStore } from '../../stores/minefieldsPreferences'
import { useShellStore } from '../../stores/shell'
import { minefieldsInactiveHint } from './minefieldsAvailability'
import {
  MINEFIELD_PAINT_POLICIES,
  MINEFIELD_PAINT_POLICY_LABELS,
  MINEFIELD_TYPE_IDS,
  MINEFIELD_TYPE_LABELS,
  type MinefieldTypeId,
} from './types'

type MinefieldsMapTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
}

export function MinefieldsMapTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
}: MinefieldsMapTileProps) {
  const inactiveReason =
    useShellStore((s) => s.gameInfoContext?.minefieldsInactiveReason) ?? null
  const available = inactiveReason == null
  const canToggle = supportsMode && available
  const showAsUnsupported = !canToggle
  const hint = available ? undefined : minefieldsInactiveHint(inactiveReason)

  const [expanded, setExpanded] = useState(false)
  const canExpand = canToggle && enabled
  const types = useMinefieldsPreferencesStore((s) => s.types)
  const setTypeEnabled = useMinefieldsPreferencesStore((s) => s.setTypeEnabled)
  const setTypePolicy = useMinefieldsPreferencesStore((s) => s.setTypePolicy)
  const setStanceInColor = useMinefieldsPreferencesStore((s) => s.setStanceInColor)
  const setStanceOutColor = useMinefieldsPreferencesStore((s) => s.setStanceOutColor)

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
        tileClassName({ supportsMode: canToggle, depressed: depressed && canToggle }),
        'flex min-w-0 max-w-full flex-col'
      )}
      title={hint}
    >
      <div className="flex items-center gap-1 py-1.5 pl-2 pr-0.5">
        <label
          className={cn(
            'flex min-w-0 flex-1 cursor-pointer items-center gap-2 py-0.5',
            showAsUnsupported && 'cursor-default'
          )}
        >
          <input
            type="checkbox"
            checked={enabled}
            onChange={() => canToggle && onToggle()}
            disabled={!canToggle}
            className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
          />
          <span className="min-w-0 truncate">{name}</span>
        </label>
        <button
          type="button"
          aria-expanded={chevronPointsDown}
          aria-label={chevronPointsDown ? 'Collapse Minefields types' : 'Expand Minefields types'}
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
        <div className="flex flex-col gap-2 border-t border-[#52575d]/40 px-2 py-2">
          {MINEFIELD_TYPE_IDS.map((typeId: MinefieldTypeId) => {
            const pref = types[typeId]
            return (
              <div key={typeId} className="flex flex-col gap-1.5">
                <label className="flex min-w-0 cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={pref.enabled}
                    onChange={(e) => setTypeEnabled(typeId, e.target.checked)}
                    className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
                  />
                  <span className="min-w-0 truncate text-xs text-slate-300">
                    {MINEFIELD_TYPE_LABELS[typeId]}
                  </span>
                </label>
                <DisplayModeControl
                  label="Color"
                  ariaLabel={`${MINEFIELD_TYPE_LABELS[typeId]} color policy`}
                  modes={MINEFIELD_PAINT_POLICIES}
                  modeLabels={MINEFIELD_PAINT_POLICY_LABELS}
                  value={pref.policy}
                  onChange={(policy) => setTypePolicy(typeId, policy)}
                />
                {pref.policy === 'stance' ? (
                  <div className="flex items-center gap-2 pl-5">
                    <label className="flex items-center gap-1 text-[11px] text-slate-400">
                      In
                      <input
                        type="color"
                        aria-label={`${MINEFIELD_TYPE_LABELS[typeId]} in-circle color`}
                        value={pref.stanceInColor}
                        onChange={(e) => setStanceInColor(typeId, e.target.value)}
                        className="h-6 w-7 shrink-0 cursor-pointer rounded border border-[#52575d] bg-transparent p-0"
                      />
                    </label>
                    <label className="flex items-center gap-1 text-[11px] text-slate-400">
                      Out
                      <input
                        type="color"
                        aria-label={`${MINEFIELD_TYPE_LABELS[typeId]} out-of-circle color`}
                        value={pref.stanceOutColor}
                        onChange={(e) => setStanceOutColor(typeId, e.target.value)}
                        className="h-6 w-7 shrink-0 cursor-pointer rounded border border-[#52575d] bg-transparent p-0"
                      />
                    </label>
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
