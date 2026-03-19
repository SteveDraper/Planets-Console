import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { cn } from '../lib/utils'
import { fetchGames } from '../api/bff'

type GameControlProps = {
  selectedGameId: string | null
  onSelectGameId: (gameId: string | null) => void
}

export function GameControl({ selectedGameId, onSelectGameId }: GameControlProps) {
  const [isOpen, setIsOpen] = useState(false)
  const [sessionExtraIds, setSessionExtraIds] = useState<string[]>([])
  const [addNewId, setAddNewId] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const { data, isPending, isError } = useQuery({
    queryKey: ['bff', 'games'],
    queryFn: fetchGames,
    enabled: isOpen,
  })

  const serverIds = (data?.games ?? []).map((g) => g.id)
  const displayIds = Array.from(new Set([...serverIds, ...sessionExtraIds])).sort()

  const closeAndReturnFocus = useCallback(() => {
    const target = returnFocusRef.current
    setIsOpen(false)
    setAddNewId('')
    if (target?.focus) {
      requestAnimationFrame(() => target.focus())
    }
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
        closeAndReturnFocus()
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
  }, [isOpen, closeAndReturnFocus])

  const selectId = (id: string) => {
    onSelectGameId(id)
    closeAndReturnFocus()
  }

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = addNewId.trim()
    if (!trimmed) return
    onSelectGameId(trimmed)
    setSessionExtraIds((prev) => (prev.includes(trimmed) ? prev : [...prev, trimmed]))
    closeAndReturnFocus()
  }

  const displayLabel = selectedGameId ?? 'None'

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        id="game-selector-trigger"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
        aria-controls={isOpen ? 'game-selector-listbox' : undefined}
        onClick={() => (isOpen ? closeAndReturnFocus() : openMenu())}
        className={cn(
          'rounded border border-transparent px-1 py-0.5 text-left text-xs text-slate-400',
          'hover:border-[#52575d] hover:bg-white/5 hover:text-slate-300',
          'focus:outline-none focus:ring-1 focus:ring-slate-400'
        )}
        title="Select game"
      >
        Game: <span className="text-slate-200">{displayLabel}</span>
      </button>
      {isOpen && (
        <div
          id="game-selector-listbox"
          role="listbox"
          aria-labelledby="game-selector-trigger"
          className={cn(
            'absolute left-0 top-full z-50 mt-1 flex min-w-[12rem] max-h-64 flex-col gap-1 overflow-y-auto',
            'rounded border border-[#52575d] bg-[#40454a] p-2 shadow-lg'
          )}
        >
          {isPending && (
            <span className="px-2 py-1 text-xs text-slate-400">Loading games…</span>
          )}
          {isError && (
            <span className="px-2 py-1 text-xs text-red-400">Failed to load games</span>
          )}
          {!isPending &&
            !isError &&
            displayIds.map((id) => (
              <button
                key={id}
                type="button"
                role="option"
                aria-selected={selectedGameId === id}
                onClick={() => selectId(id)}
                className={cn(
                  'rounded px-2 py-1.5 text-left text-xs text-slate-200',
                  'hover:bg-white/10 focus:bg-white/10 focus:outline-none'
                )}
              >
                {id}
              </button>
            ))}
          {!isPending && !isError && displayIds.length === 0 && (
            <span className="px-2 py-1 text-xs text-slate-500">No stored games</span>
          )}
          <div className="mt-1 border-t border-[#52575d] pt-2">
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
                className="rounded border border-[#52575d] bg-[#52575d] px-2 py-1 text-xs text-slate-200 hover:bg-[#5e6369]"
              >
                Add
              </button>
            </form>
            <p className="mt-1 px-1 text-[10px] leading-tight text-slate-500">
              Fetching game data from planets.nu and persisting to the store is not implemented
              yet.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
