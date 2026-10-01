import { AnalyticSidebarTile, analyticDetailCheckboxClassName } from '../AnalyticSidebarTile'
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
  const hint = available ? undefined : minefieldsInactiveHint(inactiveReason)

  const types = useMinefieldsPreferencesStore((s) => s.types)
  const setTypeEnabled = useMinefieldsPreferencesStore((s) => s.setTypeEnabled)
  const setTypePolicy = useMinefieldsPreferencesStore((s) => s.setTypePolicy)
  const setStanceInColor = useMinefieldsPreferencesStore((s) => s.setStanceInColor)
  const setStanceOutColor = useMinefieldsPreferencesStore((s) => s.setStanceOutColor)

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      available={available}
      hint={hint}
      detailsLabel="Minefields types"
    >
      {MINEFIELD_TYPE_IDS.map((typeId: MinefieldTypeId) => {
        const pref = types[typeId]
        return (
          <div key={typeId} className="flex flex-col gap-1.5">
            <label className="flex min-w-0 cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={pref.enabled}
                onChange={(e) => setTypeEnabled(typeId, e.target.checked)}
                className={analyticDetailCheckboxClassName}
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
    </AnalyticSidebarTile>
  )
}
