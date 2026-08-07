import { HullIcon } from '../../components/HullIcon'
import { usePlayerColor } from '../../stores/playerColors'
import type {
  FleetLocationRingPlayerArc,
  FleetLocationRingStack,
} from './fleetLocationRings'

function formatHostPoints(points: number): string {
  return Number.isInteger(points) ? String(points) : points.toFixed(1)
}

/** Per-player ship lines for a location-ring stack (map tooltip / planet-label footer). */
export function FleetLocationRingTooltipBody({
  stack,
}: {
  stack: FleetLocationRingStack
}) {
  return (
    <div className="font-mono text-[10px] text-slate-200">
      {stack.arcs.map((arc) => (
        <FleetLocationRingTooltipPlayer key={arc.playerId} arc={arc} />
      ))}
    </div>
  )
}

function FleetLocationRingTooltipPlayer({ arc }: { arc: FleetLocationRingPlayerArc }) {
  const color = usePlayerColor(arc.playerId)
  return (
    <div className="mb-1 last:mb-0">
      <div className="font-medium" style={{ color }}>
        {arc.playerName}
      </div>
      <ul className="mt-0.5 space-y-0.5 pl-3">
        {arc.ships.map((ship) => (
          <li key={ship.recordId} className="flex items-center gap-1.5 text-slate-300">
            {ship.hullId != null ? (
              <HullIcon hullId={ship.hullId} className="h-4 w-4 shrink-0" />
            ) : (
              <span className="inline-block h-4 w-4 shrink-0" aria-hidden />
            )}
            <span className="truncate">
              {ship.shipIdLabel} · {ship.hullLabel} ·{' '}
              {ship.hostMilitaryPoints != null
                ? `${formatHostPoints(ship.hostMilitaryPoints)} mil`
                : '— mil'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
