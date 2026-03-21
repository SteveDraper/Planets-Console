import { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp, RefreshCw } from 'lucide-react'
import { cn, mapSliderToZoom, mapZoomToSlider } from '../lib/utils'
import { useSessionStore } from '../stores/session'
import { LoginModal } from './LoginModal'
import { GameControl } from './GameControl'

type ViewMode = 'tabular' | 'map'

type HeaderProps = {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  /** Current map zoom (React Flow); drives log-scale slider. */
  mapZoom: number
  onMapZoomSliderChange: (zoom: number) => void
  selectedGameId: string | null
  /** Called when the user commits a game id (list pick or add form). Triggers BFF refresh. */
  onCommitGameSelection: (gameId: string) => void
  isGameRefreshPending: boolean
  reportShellError: (message: string) => void
  /** Max selectable turn from game info (inclusive); null if unknown or invalid. */
  shellTurnMax: number | null
  /** Selected turn in [1, shellTurnMax]; null when max is unknown. */
  shellTurnValue: number | null
  onShellTurnChange: (turn: number) => void
  /** Viewpoint entries in game order; disabled when another player's slot is not selectable. */
  shellViewpoints: { name: string; disabled: boolean }[]
  /** Current viewpoint (login default or user override). */
  shellSelectedViewpointName: string | null
  onShellViewpointChange: (name: string) => void
}

export function Header({
  viewMode,
  onViewModeChange,
  mapZoom,
  onMapZoomSliderChange,
  selectedGameId,
  onCommitGameSelection,
  isGameRefreshPending,
  reportShellError,
  shellTurnMax,
  shellTurnValue,
  onShellTurnChange,
  shellViewpoints,
  shellSelectedViewpointName,
  onShellViewpointChange,
}: HeaderProps) {
  const isMapMode = viewMode === 'map'
  const loginName = useSessionStore((s) => s.name)
  const [isLoginModalOpen, setIsLoginModalOpen] = useState(false)
  const [loginModalKey, setLoginModalKey] = useState(0)
  const [turnInputDraft, setTurnInputDraft] = useState<string | null>(null)

  const turnReady = shellTurnMax != null && shellTurnValue != null
  const committedTurnStr = shellTurnValue != null ? String(shellTurnValue) : ''

  useEffect(() => {
    setTurnInputDraft((prev) => (prev === null ? null : committedTurnStr))
  }, [committedTurnStr])

  useEffect(() => {
    if (!turnReady) setTurnInputDraft(null)
  }, [turnReady])

  const displayTurnInput = turnInputDraft ?? committedTurnStr

  const openLoginModal = () => {
    setLoginModalKey((k) => k + 1)
    setIsLoginModalOpen(true)
  }

  return (
    <header className="flex shrink-0 items-center gap-3 border-b border-[#52575d] bg-[#40454a] px-3 py-1.5 text-slate-200">
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={openLoginModal}
          className="rounded p-0.5 text-slate-400 hover:bg-white/10 hover:text-slate-300 focus:outline-none focus:ring-1 focus:ring-slate-400"
          aria-label="Change login"
          title="Change login"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
        </button>
        <span className="text-xs text-slate-400" title="Login identity">
          Login: <span className="text-slate-200">{loginName ?? '—'}</span>
        </span>
      </div>
      <LoginModal
        key={loginModalKey}
        isOpen={isLoginModalOpen}
        onClose={() => setIsLoginModalOpen(false)}
      />
      <GameControl
        selectedGameId={selectedGameId}
        onCommitGameSelection={onCommitGameSelection}
        isGameRefreshPending={isGameRefreshPending}
        reportShellError={reportShellError}
      />
      <div className="flex items-center gap-1.5" title="Turn (game year)">
        <span className="text-xs text-slate-400">Turn</span>
        {turnReady ? (
          <div className="flex items-stretch rounded border border-[#52575d] bg-[#35393e]">
            <button
              type="button"
              aria-label="Decrease turn"
              disabled={shellTurnValue <= 1}
              onClick={() => onShellTurnChange(shellTurnValue - 1)}
              className={cn(
                'flex items-center justify-center px-1 text-slate-300 hover:bg-white/10 hover:text-slate-100',
                'focus:outline-none focus-visible:ring-1 focus-visible:ring-slate-400',
                'disabled:pointer-events-none disabled:opacity-40'
              )}
            >
              <ChevronDown className="h-3.5 w-3.5" aria-hidden />
            </button>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              aria-label="Turn number"
              aria-valuemin={1}
              aria-valuemax={shellTurnMax}
              aria-valuenow={shellTurnValue}
              value={displayTurnInput}
              onChange={(e) => setTurnInputDraft(e.target.value)}
              onFocus={() => setTurnInputDraft(committedTurnStr)}
              onBlur={() => {
                setTurnInputDraft(null)
                const parsed = Number.parseInt(displayTurnInput.trim(), 10)
                if (Number.isFinite(parsed)) {
                  onShellTurnChange(parsed)
                }
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  ;(e.target as HTMLInputElement).blur()
                }
              }}
              className="w-11 border-x border-[#52575d] bg-transparent py-0.5 text-center text-xs tabular-nums text-slate-200 focus:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-slate-400"
            />
            <button
              type="button"
              aria-label="Increase turn"
              disabled={shellTurnValue >= shellTurnMax}
              onClick={() => onShellTurnChange(shellTurnValue + 1)}
              className={cn(
                'flex items-center justify-center px-1 text-slate-300 hover:bg-white/10 hover:text-slate-100',
                'focus:outline-none focus-visible:ring-1 focus-visible:ring-slate-400',
                'disabled:pointer-events-none disabled:opacity-40'
              )}
            >
              <ChevronUp className="h-3.5 w-3.5" aria-hidden />
            </button>
          </div>
        ) : (
          <span className="text-xs text-slate-400">—</span>
        )}
      </div>
      <div className="flex items-center gap-1.5" title="Viewpoint">
        <span className="text-xs text-slate-400">Viewpoint</span>
        {shellViewpoints.length > 0 && shellSelectedViewpointName != null ? (
          <select
            aria-label="Viewpoint"
            value={shellSelectedViewpointName}
            onChange={(e) => {
              const next = e.target.value
              const row = shellViewpoints.find((v) => v.name === next)
              if (row?.disabled) {
                return
              }
              onShellViewpointChange(next)
            }}
            className={cn(
              'max-w-[12rem] cursor-pointer truncate rounded border border-[#52575d] bg-[#35393e]',
              'py-0.5 pl-1 pr-6 text-xs text-slate-200',
              'focus:outline-none focus-visible:ring-1 focus-visible:ring-slate-400'
            )}
          >
            {shellViewpoints.map(({ name, disabled }, index) => (
              <option key={`${index}-${name}`} value={name} disabled={disabled}>
                {name}
              </option>
            ))}
          </select>
        ) : (
          <span className="text-xs text-slate-400">—</span>
        )}
      </div>
      <div className="ml-auto flex items-center gap-2">
        <div className="flex rounded border border-[#52575d]">
          <button
            type="button"
            onClick={() => onViewModeChange('tabular')}
            className={cn(
              'px-2.5 py-1 text-xs font-medium text-slate-200',
              viewMode === 'tabular'
                ? 'bg-[#52575d] text-slate-100'
                : 'bg-transparent text-slate-400 hover:bg-white/10 hover:text-slate-300'
            )}
          >
            Tabular
          </button>
          <button
            type="button"
            onClick={() => onViewModeChange('map')}
            className={cn(
              'px-2.5 py-1 text-xs font-medium text-slate-200',
              viewMode === 'map'
                ? 'bg-[#52575d] text-slate-100'
                : 'bg-transparent text-slate-400 hover:bg-white/10 hover:text-slate-300'
            )}
          >
            Map
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-400">Scale</span>
          <input
            type="range"
            min={0}
            max={1000}
            step={1}
            value={mapZoomToSlider(mapZoom)}
            onChange={(e) => onMapZoomSliderChange(mapSliderToZoom(Number(e.target.value)))}
            disabled={!isMapMode}
            className={cn(
              'h-1.5 w-32 accent-slate-400',
              !isMapMode && 'cursor-not-allowed opacity-50'
            )}
            title={
              isMapMode
                ? 'Map zoom — log scale: equal movement multiplies zoom by the same factor (same as scroll wheel)'
                : 'Enable map mode to use scale'
            }
          />
          <span className="w-10 text-right text-xs text-slate-400">
            {Number.isFinite(mapZoom) ? Math.round(mapZoom * 100) : 100}%
          </span>
        </div>
      </div>
    </header>
  )
}
