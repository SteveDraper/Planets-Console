import { useCallback, useEffect, useLayoutEffect, useRef, type ReactElement } from 'react'
import { cn } from '../lib/utils'
import {
  useDisplayPreferencesStore,
  type PlayerListLabelMode,
  type SectorListLabelMode,
} from '../stores/displayPreferences'

type SettingsModalProps = {
  isOpen: boolean
  onClose: () => void
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
].sort((a, b) => a.title.localeCompare(b.title))

export function SettingsModal({ isOpen, onClose }: SettingsModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const closeAndReturnFocus = useCallback(() => {
    const target = returnFocusRef.current
    onClose()
    if (target?.focus) {
      requestAnimationFrame(() => target.focus())
    }
  }, [onClose])

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

  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeAndReturnFocus()
      }
      if (e.key === 'Tab') {
        const el = dialogRef.current
        if (!el) return
        const focusables = Array.from(
          el.querySelectorAll<HTMLElement>(
            'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
          )
        )
        const len = focusables.length
        if (len === 0) return
        const i = focusables.indexOf(document.activeElement as HTMLElement)
        if (e.shiftKey) {
          if (i <= 0) {
            e.preventDefault()
            focusables[len - 1]?.focus()
          }
        } else {
          if (i === -1 || i >= len - 1) {
            e.preventDefault()
            focusables[0]?.focus()
          }
        }
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, closeAndReturnFocus])

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
