/**
 * Planet dots + route waypoints paint overlay. Hover labels and pin chrome live
 * on the **map interaction surface**; this layer stays pointer-event transparent.
 */

import { useEffect, useState } from 'react'
import { useStore } from '@xyflow/react'
import type { CombinedMapData, MapPlanetSnapshot, RouteMapWaypoint } from '../../api/bff'
import { usePlanetMapPaintState } from '../../map-interaction/contributors/PlanetMapInteraction'
import { flowCenterFromMapNode, safeZoomScale } from './geometry'

/** Fixed pixel size of the planet dot on screen (independent of zoom). */
const DOT_PIXELS = 4
/** On-screen size of a multi-hop route intermediate marker (smaller and quieter than planet dots). */
const ROUTE_WAYPOINT_CROSS_PX = 5

const LABEL_OFFSET_X_PX = 9
const LABEL_OFFSET_Y_PX = -12

/** Label text uses map payload (planet name, etc.). React Flow's internal node store does not reliably retain custom `data` fields. */
export type MapNodeLabelSource = {
  planet?: MapPlanetSnapshot
  ownerName?: string | null
  mapX: number
  mapY: number
}

export function buildLabelSourceByNodeId(nodes: CombinedMapData['nodes']): Map<string, MapNodeLabelSource> {
  const m = new Map<string, MapNodeLabelSource>()
  for (const n of nodes) {
    const payload: MapNodeLabelSource = {
      planet: n.planet,
      ownerName: n.ownerName ?? null,
      mapX: Number(n.x),
      mapY: Number(n.y),
    }
    m.set(n.id, payload)
  }
  return m
}

export function FixedSizeDotsOverlay({
  mapNodes,
  routeWaypoints,
}: {
  mapNodes: CombinedMapData['nodes']
  routeWaypoints: readonly RouteMapWaypoint[]
}) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const { hoveredWaypointId } = usePlanetMapPaintState()

  useEffect(() => {
    if (!domNode) return
    let raf = 0
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0]?.contentRect ?? { width: 0, height: 0 }
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setSize({ width, height }))
    })
    ro.observe(domNode)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [domNode])

  if (!transform || size.width <= 0 || size.height <= 0) return null
  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)

  return (
    <div className="pointer-events-none absolute inset-0 z-[5]" aria-hidden>
      <div className="absolute inset-0" aria-hidden>
        {routeWaypoints.map((w) => {
          const { cx, cy } = flowCenterFromMapNode({ x: w.gx, y: w.gy })
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          const s = ROUTE_WAYPOINT_CROSS_PX
          return (
            <div
              key={w.id}
              className="absolute text-gray-500/75"
              style={{
                left: Math.round(paneX - s / 2),
                top: Math.round(paneY - s / 2),
                width: s,
                height: s,
              }}
            >
              <svg viewBox="0 0 8 8" className="h-full w-full" aria-hidden>
                <line x1="1" y1="1" x2="7" y2="7" stroke="currentColor" strokeWidth="1.1" />
                <line x1="7" y1="1" x2="1" y2="7" stroke="currentColor" strokeWidth="1.1" />
              </svg>
            </div>
          )
        })}
      </div>
      <div className="absolute inset-0" aria-hidden>
        {mapNodes.map((mapNode) => {
          const { cx, cy } = flowCenterFromMapNode(mapNode)
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          return (
            <div
              key={`dot-${mapNode.id}`}
              className="absolute rounded-full bg-[#9ca3af]"
              style={{
                left: Math.round(paneX - DOT_PIXELS / 2),
                top: Math.round(paneY - DOT_PIXELS / 2),
                width: DOT_PIXELS,
                height: DOT_PIXELS,
              }}
            />
          )
        })}
      </div>
      <div className="absolute inset-0 z-[1]">
        {routeWaypoints.map((w) => {
          if (hoveredWaypointId !== w.id) return null
          const { cx, cy } = flowCenterFromMapNode({ x: w.gx, y: w.gy })
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          return (
            <div
              key={`wpl-${w.id}`}
              className="absolute font-mono text-gray-400"
              style={{
                left: Math.round(paneX - DOT_PIXELS / 2 + LABEL_OFFSET_X_PX),
                top: Math.round(paneY - DOT_PIXELS / 2 + LABEL_OFFSET_Y_PX),
                fontSize: 10,
                backgroundColor: '#000000',
                borderRadius: 6,
                padding: '0 4px',
              }}
            >
              {w.gx}, {w.gy}
            </div>
          )
        })}
      </div>
    </div>
  )
}
