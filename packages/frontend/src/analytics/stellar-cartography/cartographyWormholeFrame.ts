import type { CombinedMapData } from '../../api/bff'
import { STELLAR_CARTOGRAPHY_NODE_ID_PREFIX } from '../mapAnalyticIds'

export function withoutCartographyNodes(nodes: CombinedMapData['nodes']): CombinedMapData['nodes'] {
  return nodes.filter((node) => !node.id.startsWith(STELLAR_CARTOGRAPHY_NODE_ID_PREFIX))
}

export function collectWormholeEndpoints(
  nodes: CombinedMapData['nodes'],
  unknownEntrances: CombinedMapData['wormholeUnknownEntrances']
): { x: number; y: number }[] {
  const seen = new Set<string>()
  const endpoints: { x: number; y: number }[] = []
  const add = (x: number, y: number) => {
    const key = `${x},${y}`
    if (seen.has(key)) return
    seen.add(key)
    endpoints.push({ x, y })
  }
  for (const node of nodes) {
    if (node.id.startsWith(STELLAR_CARTOGRAPHY_NODE_ID_PREFIX)) {
      add(Number(node.x), Number(node.y))
    }
  }
  for (const entrance of unknownEntrances) {
    add(entrance.x, entrance.y)
  }
  return endpoints
}
