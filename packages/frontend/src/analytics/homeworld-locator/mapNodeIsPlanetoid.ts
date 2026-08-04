import type { MapNode } from '../../api/bff'

/** Coerce host ``debrisdisk`` (number or numeric string) for planetoid checks. */
function debrisdiskValue(raw: unknown): number | null {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && raw.trim() !== '') {
    const parsed = Number(raw)
    if (Number.isFinite(parsed)) return parsed
  }
  return null
}

/** True when the map node is a planetoid (`debrisdisk == 1`), matching Core `planet_is_planetoid`. */
export function mapNodeIsPlanetoid(node: Pick<MapNode, 'planet'>): boolean {
  return debrisdiskValue(node.planet?.debrisdisk) === 1
}

/**
 * Whether a planet spatial hit should open the homeworld planet context menu.
 * Missing nodes fail closed (no planet menu). Planetoids never open a planet menu.
 */
export function shouldOpenHomeworldPlanetMenu(node: MapNode | undefined): boolean {
  if (node == null) return false
  return !mapNodeIsPlanetoid(node)
}

/**
 * Planetoid under the cursor: suppress planet and sector homeworld menus.
 * Right-click empty map space (or a traditional planet) can still open sector menus.
 */
export function shouldSuppressHomeworldMenusForPlanetHit(
  node: MapNode | undefined
): boolean {
  return node != null && mapNodeIsPlanetoid(node)
}
