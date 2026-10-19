/**
 * Player-territory fills use the shared per-player palette and ignore
 * global diplomacy color mode, the same rule as minefield owner paint.
 */

import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { isPlayerTerritoryKind } from './kinds'
import {
  colorFromOverrideOrDefault,
  playerColorOverrideStorageKey,
  type PlayerColorPaintSnapshot,
} from '../../lib/playerColor'

export function playerTerritoryFillColor(
  playerId: number,
  snapshot: PlayerColorPaintSnapshot
): string {
  return colorFromOverrideOrDefault(
    playerId,
    snapshot.overrides[playerColorOverrideStorageKey(playerId)]
  )
}

/** Replace placeholder ``fillColor`` on player-territory overlays. Other kinds pass through. */
export function applyPlayerTerritoryFillColors(
  overlays: readonly MapRegionOverlay[],
  snapshot: PlayerColorPaintSnapshot
): MapRegionOverlay[] {
  let changed = false
  const painted = overlays.map((overlay) => {
    if (!isPlayerTerritoryKind(overlay.kind) || overlay.playerId == null) return overlay
    const fillColor = playerTerritoryFillColor(overlay.playerId, snapshot)
    if (overlay.fillColor === fillColor && overlay.fillPattern === 'solid') return overlay
    changed = true
    return { ...overlay, fillColor, fillPattern: 'solid' as const }
  })
  return changed ? painted : (overlays as MapRegionOverlay[])
}
