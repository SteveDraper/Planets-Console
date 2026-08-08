import { useCallback, useLayoutEffect, useRef, type ReactElement } from 'react'
import { useModalKeydownFocusTrap } from '../lib/modalKeydownFocusTrap'
import { restoreFocusToElementOrFallback } from '../lib/restoreFocus'
import { cn } from '../lib/utils'
import {
  DIPLOMACY_COLOR_THRESHOLD_OPTIONS,
  isDiplomacyColorThreshold,
} from '../lib/diplomacyTier'
import { formatViewpointRowLabel } from '../lib/displayFormatters'
import {
  defaultColorForPlayerId,
  isPlayerColorMode,
} from '../lib/playerColor'
import {
  useDisplayPreferencesStore,
  type PlayerListLabelMode,
  type SectorListLabelMode,
} from '../stores/displayPreferences'
import { usePlayerColorsStore } from '../stores/playerColors'
import { useShellStore } from '../stores/shell'

type SettingsModalProps = {
  isOpen: boolean
  onClose: () => void
  /** When the opener (e.g. a menu item) unmounts before close, focus moves here instead. */
  getFocusRestoreFallback?: () => HTMLElement | null
}

const PLAYER_LABEL_OPTIONS: { value: PlayerListLabelMode; label: string }[] = [
  { value: 'player_names_only', label: 'Player names only' },
  { value: 'race_names_only', label: 'Race names only' },
  { value: 'player_and_race_names', label: 'Both player and race names' },
]

const SECTOR_LABEL_OPTIONS: { value: SectorListLabelMode; label: string }[] = [
  { value: 'sector_ids_only', label: 'Sector ids only' },
  { value: 'sector_names_only', label: 'Sector names only' },
  { value: 'both_ids_and_names', label: 'Both ids and names' },
]

const selectClassName = cn(
  'w-full max-w-xs rounded border border-[#52575d] bg-[#2b2e32] px-2 py-1.5 text-xs text-slate-200',
  'focus:border-slate-400 focus:outline-none'
)

function DisplayOptionsSection() {
  const playerListLabelMode = useDisplayPreferencesStore((s) => s.playerListLabelMode)
  const sectorListLabelMode = useDisplayPreferencesStore((s) => s.sectorListLabelMode)
  const setPlayerListLabelMode = useDisplayPreferencesStore((s) => s.setPlayerListLabelMode)
  const setSectorListLabelMode = useDisplayPreferencesStore((s) => s.setSectorListLabelMode)

  return (
    <div className="flex flex-col gap-3 pt-2">
      <div className="flex flex-col gap-1">
        <label htmlFor="settings-player-label-mode" className="text-xs text-slate-400">
          Display players as
        </label>
        <select
          id="settings-player-label-mode"
          value={playerListLabelMode}
          onChange={(e) =>
            setPlayerListLabelMode(e.target.value as PlayerListLabelMode)
          }
          className={selectClassName}
        >
          {PLAYER_LABEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="settings-sector-label-mode" className="text-xs text-slate-400">
          Display sectors as
        </label>
        <select
          id="settings-sector-label-mode"
          value={sectorListLabelMode}
          onChange={(e) =>
            setSectorListLabelMode(e.target.value as SectorListLabelMode)
          }
          className={selectClassName}
        >
          {SECTOR_LABEL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

function PlayerColorsSection() {
  const playerListLabelMode = useDisplayPreferencesStore((s) => s.playerListLabelMode)
  const perspectives = useShellStore((s) => s.gameInfoContext?.perspectives)
  const mode = usePlayerColorsStore((s) => s.mode)
  const diplomacyThreshold = usePlayerColorsStore((s) => s.diplomacyThreshold)
  const familyBaseColor = usePlayerColorsStore((s) => s.familyBaseColor)
  const outOfCircleBaseColor = usePlayerColorsStore((s) => s.outOfCircleBaseColor)
  const overrides = usePlayerColorsStore((s) => s.overrides)
  const setPlayerColorMode = usePlayerColorsStore((s) => s.setPlayerColorMode)
  const setDiplomacyThreshold = usePlayerColorsStore((s) => s.setDiplomacyThreshold)
  const setFamilyBaseColor = usePlayerColorsStore((s) => s.setFamilyBaseColor)
  const setOutOfCircleBaseColor = usePlayerColorsStore((s) => s.setOutOfCircleBaseColor)
  const setPlayerColorOverride = usePlayerColorsStore((s) => s.setPlayerColorOverride)

  return (
    <div className="flex flex-col gap-3 pt-2">
      <div className="flex flex-col gap-1">
        <label htmlFor="settings-player-color-mode" className="text-xs text-slate-400">
          Color by
        </label>
        <select
          id="settings-player-color-mode"
          value={mode}
          onChange={(e) => {
            if (isPlayerColorMode(e.target.value)) {
              setPlayerColorMode(e.target.value)
            }
          }}
          className={selectClassName}
        >
          <option value="per_player">Per player</option>
          <option value="diplomacy_family">Diplomacy family</option>
        </select>
      </div>

      {mode === 'diplomacy_family' ? (
        <>
          <div className="flex flex-col gap-1">
            <label
              htmlFor="settings-diplomacy-color-threshold"
              className="text-xs text-slate-400"
            >
              Minimum inbound status
            </label>
            <select
              id="settings-diplomacy-color-threshold"
              value={diplomacyThreshold}
              onChange={(e) => {
                const next = Number(e.target.value)
                if (isDiplomacyColorThreshold(next)) {
                  setDiplomacyThreshold(next)
                }
              }}
              className={selectClassName}
            >
              {DIPLOMACY_COLOR_THRESHOLD_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <label
              htmlFor="settings-family-base-color"
              className="text-xs text-slate-400"
            >
              Diplomacy circle base
            </label>
            <input
              id="settings-family-base-color"
              type="color"
              aria-label="Diplomacy circle base color"
              value={familyBaseColor}
              onChange={(e) => setFamilyBaseColor(e.target.value)}
              className="h-8 w-12 cursor-pointer rounded border border-[#52575d] bg-transparent p-0"
            />
          </div>
          <div className="flex flex-col gap-1">
            <label
              htmlFor="settings-out-of-circle-base-color"
              className="text-xs text-slate-400"
            >
              Others base
            </label>
            <input
              id="settings-out-of-circle-base-color"
              type="color"
              aria-label="Others base color"
              value={outOfCircleBaseColor}
              onChange={(e) => setOutOfCircleBaseColor(e.target.value)}
              className="h-8 w-12 cursor-pointer rounded border border-[#52575d] bg-transparent p-0"
            />
          </div>
        </>
      ) : perspectives == null || perspectives.length === 0 ? (
        <p className="text-xs text-slate-400">Load a game to set player colors.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {perspectives.map((row) => {
            const key = String(row.playerId)
            const override = overrides[key]
            const effective = override ?? defaultColorForPlayerId(row.playerId)
            const label = formatViewpointRowLabel(
              playerListLabelMode,
              row.name,
              row.raceName
            )
            return (
              <li
                key={row.playerId}
                className="flex items-center gap-2 text-xs text-slate-200"
              >
                <span className="min-w-0 flex-1 truncate">{label}</span>
                <input
                  type="color"
                  aria-label={`Color for ${label}`}
                  value={effective}
                  onChange={(e) => setPlayerColorOverride(row.playerId, e.target.value)}
                  className="h-6 w-7 shrink-0 cursor-pointer rounded border border-[#52575d] bg-transparent p-0"
                />
                <button
                  type="button"
                  className="shrink-0 rounded px-1.5 py-0.5 text-[10px] text-slate-400 hover:bg-white/10 hover:text-slate-200 disabled:opacity-40"
                  disabled={override == null}
                  onClick={() => setPlayerColorOverride(row.playerId, null)}
                >
                  Reset
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

type SettingsSectionDef = {
  id: string
  title: string
  Content: () => ReactElement
}

const SETTINGS_SECTIONS: SettingsSectionDef[] = [
  {
    id: 'display-options',
    title: 'Display Options',
    Content: DisplayOptionsSection,
  },
  {
    id: 'player-colors',
    title: 'Player Colors',
    Content: PlayerColorsSection,
  },
].sort((a, b) => a.title.localeCompare(b.title))

export function SettingsModal({
  isOpen,
  onClose,
  getFocusRestoreFallback,
}: SettingsModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const closeAndReturnFocus = useCallback(() => {
    const target = returnFocusRef.current
    onClose()
    restoreFocusToElementOrFallback(target, getFocusRestoreFallback)
  }, [onClose, getFocusRestoreFallback])

  useLayoutEffect(() => {
    if (!isOpen) return
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    const el = dialogRef.current
    if (!el) return
    const focusables = el.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    focusables[0]?.focus()
  }, [isOpen])

  useModalKeydownFocusTrap(isOpen, dialogRef, closeAndReturnFocus)

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      aria-hidden="false"
      onClick={(e) => {
        if (e.target === e.currentTarget) {
          closeAndReturnFocus()
        }
      }}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-dialog-title"
        onClick={(e) => e.stopPropagation()}
        className={cn(
          'flex max-h-[min(90vh,32rem)] w-full max-w-lg flex-col gap-3 overflow-y-auto',
          'rounded border border-[#52575d] bg-[#40454a] p-4 shadow-lg',
          'focus:outline-none'
        )}
      >
        <div className="flex items-start justify-between gap-2">
          <h2 id="settings-dialog-title" className="text-sm font-medium text-slate-200">
            Settings
          </h2>
          <button
            type="button"
            onClick={closeAndReturnFocus}
            className="rounded px-2 py-1 text-xs text-slate-400 hover:bg-white/10 hover:text-slate-200"
          >
            Close
          </button>
        </div>
        <div className="flex flex-col gap-2">
          {SETTINGS_SECTIONS.map(({ id, title, Content }) => (
            <details
              key={id}
              className="rounded border border-[#52575d] bg-[#35393e] px-2 py-1"
            >
              <summary className="cursor-pointer select-none text-xs font-medium text-slate-200">
                {title}
              </summary>
              <Content />
            </details>
          ))}
        </div>
      </div>
    </div>
  )
}
