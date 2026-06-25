import { useEffect, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import { orderFleetSidebarPlayers } from './fleetPlayerVisibilityPolicy'
import { tileClassName } from '../tileChrome'

type FleetAnalyticTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  players: PerspectiveRow[]
  viewpointPlayerId: number | null
}

export function FleetAnalyticTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  players,
  viewpointPlayerId,
}: FleetAnalyticTileProps) {
  const [expanded, setExpanded] = useState(false)
  const canExpand = supportsMode && enabled && players.length > 0
  const isFleetPlayerVisible = useFleetPlayerVisibilityStore((state) => state.isFleetPlayerVisible)
  const setFleetPlayerVisible = useFleetPlayerVisibilityStore((state) => state.setFleetPlayerVisible)
  const orderedPlayers = orderFleetSidebarPlayers(players, viewpointPlayerId)

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
            chevronPointsDown ? 'Collapse Fleet player visibility' : 'Expand Fleet player visibility'
          }
          disabled={!canExpand}
          onClick={() => canExpand && setExpanded((value) => !value)}
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
        <div
          className="flex min-w-0 flex-col gap-1 border-t border-[#52575d]/70 px-2 pb-2 pt-1.5 text-xs text-slate-300"
          onClick={(event) => event.stopPropagation()}
        >
          {orderedPlayers.map((player) => (
            <label key={player.playerId} className="flex cursor-pointer items-center gap-2">
              <input
                type="checkbox"
                checked={isFleetPlayerVisible(player.playerId, viewpointPlayerId)}
                onChange={(event) =>
                  setFleetPlayerVisible(player.playerId, event.target.checked)
                }
                className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 accent-slate-400"
              />
              <span className="min-w-0 truncate">{player.name}</span>
            </label>
          ))}
        </div>
      ) : null}
    </div>
  )
}
