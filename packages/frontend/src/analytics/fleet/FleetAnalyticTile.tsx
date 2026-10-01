import { useMemo } from 'react'
import type { AnalyticShellScope } from '../../api/bff'
import { deriveShellTurnMax, deriveTurnView } from '../../shell/shellContext'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import { useTurnRacePlayerLabels } from '../../lib/turnRacePlayerLabels'
import { cn } from '../../lib/utils'
import { useFleetPlayerVisibilityStore } from '../../stores/fleetPlayerVisibility'
import {
  FLEET_HEADING_TRAIL_MAX_EXTEND_TURNS,
  useFleetHeadingTrailExtendStore,
} from '../../stores/fleetHeadingTrailExtend'
import { usePlayerColor } from '../../stores/playerColors'
import { useShellStore } from '../../stores/shell'
import { fleetPlayerDisplayLabel } from './fleetPlayerDisplayLabel'
import { useOrderedFleetPlayers } from './useOrderedFleetPlayers'
import { AnalyticSidebarTile } from '../AnalyticSidebarTile'

const TRAIL_EXTEND_OPTIONS = Array.from(
  { length: FLEET_HEADING_TRAIL_MAX_EXTEND_TURNS + 1 },
  (_, n) => n
)

type FleetAnalyticTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  analyticScope: AnalyticShellScope | null
}

type FleetPlayerVisibilityRowProps = {
  player: Pick<PerspectiveRow, 'playerId' | 'name' | 'raceName'>
  racePlayerLabels: Map<number, string>
  isVisible: boolean
  onVisibleChange: (visible: boolean) => void
}

function FleetPlayerVisibilityRow({
  player,
  racePlayerLabels,
  isVisible,
  onVisibleChange,
}: FleetPlayerVisibilityRowProps) {
  const color = usePlayerColor(player.playerId)
  const playerLabel = fleetPlayerDisplayLabel(player, racePlayerLabels, undefined)

  return (
    <label
      title={playerLabel}
      className="flex cursor-pointer items-center gap-2"
    >
      <input
        type="checkbox"
        checked={isVisible}
        onChange={(event) => onVisibleChange(event.target.checked)}
        className="h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
      />
      <span
        aria-hidden
        data-testid={`fleet-player-color-${player.playerId}`}
        className={cn(
          'h-2.5 w-2.5 shrink-0 rounded-sm border border-black/40',
          !isVisible && 'opacity-50'
        )}
        style={{ backgroundColor: color }}
      />
      <span className="min-w-0 truncate">{playerLabel}</span>
    </label>
  )
}

export function FleetAnalyticTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  analyticScope,
}: FleetAnalyticTileProps) {
  const gameInfoContext = useShellStore((s) => s.gameInfoContext)
  const selectedTurn = useShellStore((s) => s.selectedTurn)
  const { players: orderedPlayers, isPlayerVisible } = useOrderedFleetPlayers()
  const setFleetPlayerVisible = useFleetPlayerVisibilityStore((state) => state.setFleetPlayerVisible)
  const trailExtendTurns = useFleetHeadingTrailExtendStore((state) => state.extendTurns)
  const setTrailExtendTurns = useFleetHeadingTrailExtendStore((state) => state.setExtendTurns)
  const shellTurnMax = useMemo(
    () => deriveShellTurnMax(gameInfoContext),
    [gameInfoContext]
  )
  const { isFuture } = useMemo(
    () => deriveTurnView(selectedTurn, shellTurnMax),
    [selectedTurn, shellTurnMax]
  )
  const racePlayerLabels = useTurnRacePlayerLabels(analyticScope, supportsMode && enabled)

  return (
    <AnalyticSidebarTile
      name={name}
      enabled={enabled}
      supportsMode={supportsMode}
      depressed={depressed}
      onToggle={onToggle}
      canExpand={orderedPlayers.length > 0}
      detailsLabel="Fleet player visibility"
    >
      <label className="flex min-w-0 w-full items-center gap-1.5">
        <span className="w-11 shrink-0 text-slate-400">Trail</span>
        <select
          aria-label="Fleet heading trail extend turns"
          title={
            isFuture
              ? 'Heading trails are hidden on future turns (no movement simulation beyond the hosted turn).'
              : 'Extra turns of heading trail beyond the current turn (0 = current turn only). Forward and backward segments fade with distance.'
          }
          value={trailExtendTurns}
          onChange={(event) => setTrailExtendTurns(Number(event.target.value))}
          disabled={isFuture}
          className="min-w-0 w-0 flex-1 rounded border border-[#52575d] bg-[#2a2d30] px-1 py-0.5 text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {TRAIL_EXTEND_OPTIONS.map((n) => (
            <option key={n} value={n}>
              {n === 0 ? '0 (current only)' : String(n)}
            </option>
          ))}
        </select>
      </label>
      {orderedPlayers.map((player) => (
        <FleetPlayerVisibilityRow
          key={player.playerId}
          player={player}
          racePlayerLabels={racePlayerLabels}
          isVisible={isPlayerVisible(player.playerId)}
          onVisibleChange={(visible) => setFleetPlayerVisible(player.playerId, visible)}
        />
      ))}
    </AnalyticSidebarTile>
  )
}
