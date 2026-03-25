import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchGames } from '../api/bff'
import { formatStoredGameRowLabel } from '../lib/displayFormatters'
import { restoreFocusToElementOrFallback } from '../lib/restoreFocus'
import { cn } from '../lib/utils'
import { useDisplayPreferencesStore } from '../stores/displayPreferences'
import { useShellStore } from '../stores/shell'

type GameControlProps = {
  selectedGameId: string | null
  onCommitGameSelection: (gameId: string) => void
  isGameRefreshPending: boolean
  /** Append a dismissible shell error (e.g. games list fetch failed). */
  reportShellError: (message: string) => void
}

export function GameControl({
  selectedGameId,
  onCommitGameSelection,
  isGameRefreshPending,
  reportShellError,
}: GameControlProps) {
  const sectorListLabelMode = useDisplayPreferencesStore((s) => s.sectorListLabelMode)
  const sectorDisplayName = useShellStore((s) => s.gameInfoContext?.sectorDisplayName ?? null)
  const idRoot = useId()
  const triggerId = `${idRoot}-game-selector-trigger`
  const popoverId = `${idRoot}-game-selector-popover`

  const [isOpen, setIsOpen] = useState(false)
  const [sessionExtraIds, setSessionExtraIds] = useState<string[]>([])
  const [addNewId, setAddNewId] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)
  const gameTriggerRef = useRef<HTMLButtonElement>(null)

  const { data, isPending, isError, error: gamesQueryError } = useQuery({
    queryKey: ['bff', 'games'],
    queryFn: fetchGames,
    enabled: isOpen,
  })

  const gamesListFailureSeen = useRef(false)
  useEffect(() => {
    if (isError) {
      if (!gamesListFailureSeen.current) {
        gamesListFailureSeen.current = true
        reportShellError(
          gamesQueryError instanceof Error
            ? gamesQueryError.message
            : 'Failed to load games list'
        )
      }
    } else {
      gamesListFailureSeen.current = false
    }
  }, [isError, gamesQueryError, reportShellError])

  const sectorNameById = useMemo(() => {
    const m = new Map<string, string>()
    for (const g of data?.games ?? []) {
      const sn = g.sectorName?.trim()
      if (sn) {
        m.set(g.id, sn)
      }
    }
    return m
  }, [data?.games])

  const serverIds = (data?.games ?? []).map((g) => g.id)
  const displayIds = Array.from(new Set([...serverIds, ...sessionExtraIds])).sort()

  /** Dismiss without moving focus; used for outside pointerdown so the clicked control keeps focus. */
  const closeWithoutFocusRestore = useCallback(() => {
    setIsOpen(false)
    setAddNewId('')
  }, [])

  const closeAndReturnFocus = useCallback(() => {
    const target = returnFocusRef.current
    setIsOpen(false)
    setAddNewId('')
    restoreFocusToElementOrFallback(target, () => gameTriggerRef.current)
  }, [])

  const openMenu = () => {
    returnFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    setIsOpen(true)
  }

  useEffect(() => {
    if (!isOpen) return
    const onPointerDown = (e: MouseEvent) => {
      const el = containerRef.current
      if (el && !el.contains(e.target as Node)) {
        closeWithoutFocusRestore()
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        closeAndReturnFocus()
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [isOpen, closeAndReturnFocus, closeWithoutFocusRestore])

  const selectId = (id: string) => {
    onCommitGameSelection(id)
    closeAndReturnFocus()
  }

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = addNewId.trim()
    if (!trimmed) return
    onCommitGameSelection(trimmed)
    setSessionExtraIds((prev) => (prev.includes(trimmed) ? prev : [...prev, trimmed]))
    closeAndReturnFocus()
  }

  const displayLabel = isGameRefreshPending
    ? 'Refreshing…'
    : selectedGameId == null
      ? 'None'
      : formatStoredGameRowLabel(
          sectorListLabelMode,
          selectedGameId,
          sectorDisplayName ?? sectorNameById.get(selectedGameId)
        )

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={gameTriggerRef}
        type="button"
        id={triggerId}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        aria-controls={isOpen ? popoverId : undefined}
        onClick={() => (isOpen ? closeAndReturnFocus() : openMenu())}
        className={cn(
          'rounded border border-transparent px-1 py-0.5 text-left text-xs text-slate-400',
          'hover:border-[#52575d] hover:bg-white/5 hover:text-slate-300',
          'focus:outline-none focus:ring-1 focus:ring-slate-400'
        )}
        title="Select game"
        disabled={isGameRefreshPending}
      >
        Game: <span className="text-slate-200">{displayLabel}</span>
      </button>
      {isOpen && (
        <div
          id={popoverId}
          role="dialog"
          aria-modal="false"
          aria-labelledby={triggerId}
          className={cn(
            'absolute left-0 top-full z-50 mt-1 flex min-w-[12rem] max-h-64 flex-col gap-1 overflow-y-auto',
            'rounded border border-[#52575d] bg-[#40454a] p-2 shadow-lg'
          )}
        >
          {isPending && (
            <span className="px-2 py-1 text-xs text-slate-400" role="status">
              Loading games…
            </span>
          )}
          {isError && (
            <span className="px-2 py-1 text-xs text-slate-500" role="status">
              Could not load list (see error bar)
            </span>
          )}
          {!isPending && !isError && displayIds.length > 0 && (
            <ul
              aria-label="Stored games"
              className="m-0 flex list-none flex-col gap-1 p-0"
            >
              {displayIds.map((id) => {
                const isSelected = selectedGameId === id
                const rowLabel = formatStoredGameRowLabel(
                  sectorListLabelMode,
                  id,
                  sectorNameById.get(id)
                )
                return (
                  <li key={id}>
                    <button
                      type="button"
                      onClick={() => selectId(id)}
                      disabled={isGameRefreshPending}
                      aria-current={isSelected ? true : undefined}
                      className={cn(
                        'w-full rounded px-2 py-1.5 text-left text-xs text-slate-200',
                        'hover:bg-white/10 focus:bg-white/10 focus:outline-none',
                        'disabled:cursor-not-allowed disabled:opacity-50',
                        isSelected && 'bg-white/10 ring-1 ring-slate-500/60'
                      )}
                    >
                      {rowLabel}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
          {!isPending && !isError && displayIds.length === 0 && (
            <span className="px-2 py-1 text-xs text-slate-500">No stored games</span>
          )}
          <div
            role="group"
            aria-label="Add game by id"
            className="mt-1 border-t border-[#52575d] pt-2"
          >
            <p className="mb-1 px-1 text-[10px] uppercase tracking-wide text-slate-500">
              Add game (id only)
            </p>
            <form onSubmit={handleAddSubmit} className="flex flex-col gap-1.5">
              <input
                type="text"
                value={addNewId}
                onChange={(e) => setAddNewId(e.target.value)}
                placeholder="Game id"
                className="rounded border border-[#52575d] bg-[#2b2e32] px-2 py-1 text-xs text-slate-200 placeholder:text-slate-500 focus:border-slate-400 focus:outline-none"
                aria-label="New game id"
              />
              <button
                type="submit"
                disabled={isGameRefreshPending}
                className="rounded border border-[#52575d] bg-[#52575d] px-2 py-1 text-xs text-slate-200 hover:bg-[#5e6369] disabled:cursor-not-allowed disabled:opacity-50"
              >
                Add
              </button>
            </form>
            <p className="mt-1 px-1 text-[10px] leading-tight text-slate-500">
              Choosing a game loads the latest game info from planets.nu into the store.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
