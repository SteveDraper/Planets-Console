import type { MapNode } from '../../api/bff'

/** True when the map node is a planetoid (`debrisdisk == 1`), matching Core `planet_is_planetoid`. */
export function mapNodeIsPlanetoid(node: Pick<MapNode, 'planet'>): boolean {
  const debrisdisk = node.planet?.debrisdisk
  return typeof debrisdisk === 'number' && debrisdisk === 1
}

/**
 * Whether a planet spatial hit should open the homeworld planet context menu.
 * Planetoids fall through to sector resolution (or dismiss).
 */
export function shouldOpenHomeworldPlanetMenu(node: MapNode | undefined): boolean {
  if (node == null) return true
  return !mapNodeIsPlanetoid(node)
}
