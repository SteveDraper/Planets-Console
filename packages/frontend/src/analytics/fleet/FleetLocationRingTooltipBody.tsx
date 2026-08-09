/**
 * Per-player ship lines for a location-ring stack (map tooltip / planet-label footer).
 *
 * Hull names resolve from the live component catalog at render time so labels update
 * when the catalog arrives after stacks were first projected (empty-catalog bake).
 */

import { HullIcon } from '../../components/HullIcon'
import type { AnalyticShellScope } from '../../api/bff'
import { usePlayerColor } from '../../stores/playerColors'
import {
  type FleetComponentCatalog,
  fleetHullName,
} from './fleetComponentCatalog'
import type {
  FleetLocationRingPlayerArc,
  FleetLocationRingShip,
  FleetLocationRingStack,
} from './fleetLocationRings'
import { useFleetComponentCatalogQuery } from './useFleetComponentCatalogQuery'

function formatHostPoints(points: number): string {
  return Number.isInteger(points) ? String(points) : points.toFixed(1)
}

function fleetHoverHullLabel(
  ship: FleetLocationRingShip,
  catalog: FleetComponentCatalog
): string {
  if (ship.hullId != null) {
    return fleetHullName(catalog, ship.hullId) ?? ship.hullLabel
  }
  return ship.hullLabel
}

/** Warp suffix for map hover ship lines: ``(w9)`` when known, ``(-)`` when motionless/unknown. */
export function formatFleetHoverWarpLabel(warp: number | null): string {
  return warp != null ? `(w${warp})` : '(-)'
}

export function FleetLocationRingTooltipBody({
  stack,
  analyticScope,
}: {
  stack: FleetLocationRingStack
  analyticScope: AnalyticShellScope | null
}) {
  const componentCatalog = useFleetComponentCatalogQuery(
    analyticScope,
    analyticScope != null
  )

  return (
    <div className="font-mono text-[10px] text-slate-200">
      {stack.arcs.map((arc) => (
        <FleetLocationRingTooltipPlayer
          key={arc.playerId}
          arc={arc}
          componentCatalog={componentCatalog}
        />
      ))}
    </div>
  )
}

function FleetLocationRingTooltipPlayer({
  arc,
  componentCatalog,
}: {
  arc: FleetLocationRingPlayerArc
  componentCatalog: FleetComponentCatalog
}) {
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
              {ship.shipIdLabel} · {fleetHoverHullLabel(ship, componentCatalog)}{' '}
              {formatFleetHoverWarpLabel(ship.warp)} ·{' '}
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
