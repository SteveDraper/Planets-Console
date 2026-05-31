import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useStore } from '@xyflow/react'
import type { CombinedMapData, MapPlanetSnapshot, RouteMapWaypoint } from '../../api/bff'
import {
  findClosestPlanetWithinRadius,
  flowCenterToPlanet,
  type PlanetSpatialGrid,
} from '../../lib/planetSpatialGrid'
import { cn } from '../../lib/utils'
import { PlanetMapLabel } from '../PlanetMapLabel'
import {
  planetLabelOptionsShowAnyLabel,
  type PlanetLabelOptions,
} from '../planetMapLabelModel'
import {
  clientToFlowPosition,
  flowCenterFromMapNode,
  safeZoomScale,
} from './geometry'

/** Fixed pixel size of the planet dot on screen (independent of zoom). */
const DOT_PIXELS = 4
/** On-screen size of a multi-hop route intermediate marker (smaller and quieter than planet dots). */
const ROUTE_WAYPOINT_CROSS_PX = 5
/** Mouse distance from dot center (px) at which the planet label is shown. */
const PLANET_LABEL_HOVER_RADIUS_PX = 14

/**
 * in size regardless of zoom. Uses same flow->pane conversion as the grid.
 */
const HOVER_CLIENT_MOVE_EPS_PX = 0.5

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
  planetGrid,
  planetLabelOptions,
  labelSourceByNodeId,
  mapNodes,
  routeWaypoints,
  waypointGrid,
  onPlanetLabelHoverActiveChange,
}: {
  planetGrid: PlanetSpatialGrid | null
  planetLabelOptions: PlanetLabelOptions
  labelSourceByNodeId: Map<string, MapNodeLabelSource>
  mapNodes: CombinedMapData['nodes']
  routeWaypoints: readonly RouteMapWaypoint[]
  /** Sub-linear hover: same map-cell + radius model as :func:`buildPlanetSpatialGrid` for planets. */
  waypointGrid: PlanetSpatialGrid | null
  onPlanetLabelHoverActiveChange?: (active: boolean) => void
}) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [hoveredWaypointId, setHoveredWaypointId] = useState<string | null>(null)
  const [pinnedNodeId, setPinnedNodeId] = useState<string | null>(null)
  const hoverRafRef = useRef<number | null>(null)
  const pendingClientRef = useRef<{ x: number; y: number } | null>(null)
  const lastProcessedClientRef = useRef<{ x: number; y: number } | null>(null)
  const transformRef = useRef(transform)
  const pinnedNodeIdRef = useRef<string | null>(null)
  useLayoutEffect(() => {
    transformRef.current = transform
  }, [transform])
  useLayoutEffect(() => {
    pinnedNodeIdRef.current = pinnedNodeId
  }, [pinnedNodeId])

  const showAnyLabelOption = planetLabelOptionsShowAnyLabel(planetLabelOptions)

  const planetLabelHoverActive =
    pinnedNodeId != null || (showAnyLabelOption && hoveredNodeId != null)

  useEffect(() => {
    onPlanetLabelHoverActiveChange?.(planetLabelHoverActive)
  }, [onPlanetLabelHoverActiveChange, planetLabelHoverActive])

  const mapNodeIdsKey = useMemo(() => mapNodes.map((n) => n.id).join('\0'), [mapNodes])

  useEffect(() => {
    setPinnedNodeId(null)
  }, [mapNodeIdsKey])

  useEffect(() => {
    if (!showAnyLabelOption) {
      setPinnedNodeId(null)
    }
  }, [showAnyLabelOption])

  useEffect(() => {
    if (pinnedNodeId == null) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPinnedNodeId(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [pinnedNodeId])

  useEffect(() => {
    if (pinnedNodeId != null) {
      setHoveredNodeId(null)
      setHoveredWaypointId(null)
    }
  }, [pinnedNodeId])

  const routeWaypointIdSet = useMemo(
    () => new Set(routeWaypoints.map((w) => w.id)),
    [routeWaypoints]
  )
  const hoveredWaypointInList =
    hoveredWaypointId != null && routeWaypointIdSet.has(hoveredWaypointId)
  const hoveredWaypointIdForLabel =
    pinnedNodeId == null && hoveredWaypointInList ? hoveredWaypointId : null

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

  useEffect(() => {
    const el = domNode
    if (!el || size.width <= 0 || size.height <= 0) return

    if (!planetGrid && !waypointGrid) {
      return
    }

    const runHitTest = (clientX: number, clientY: number) => {
      if (pinnedNodeIdRef.current != null) return
      const t = transformRef.current
      if (!t) {
        setHoveredNodeId(null)
        setHoveredWaypointId(null)
        return
      }
      const paneRect = el.getBoundingClientRect()
      const flow = clientToFlowPosition(clientX, clientY, el, t, paneRect)
      if (!flow) {
        setHoveredNodeId(null)
        setHoveredWaypointId(null)
        return
      }
      const rawScale = t[2]
      const scale = safeZoomScale(rawScale)
      const radiusFlow = PLANET_LABEL_HOVER_RADIUS_PX / scale
      if (planetGrid) {
        const { px, py } = flowCenterToPlanet(flow.x, flow.y)
        const closestId = findClosestPlanetWithinRadius(planetGrid, px, py, radiusFlow)
        if (closestId != null) {
          setHoveredNodeId(closestId)
          setHoveredWaypointId(null)
          return
        }
      }
      setHoveredNodeId(null)
      if (waypointGrid) {
        const { px, py } = flowCenterToPlanet(flow.x, flow.y)
        setHoveredWaypointId(findClosestPlanetWithinRadius(waypointGrid, px, py, radiusFlow))
      } else {
        setHoveredWaypointId(null)
      }
    }

    const flushHover = () => {
      const p = pendingClientRef.current
      if (!p) return
      const last = lastProcessedClientRef.current
      if (
        last &&
        Math.abs(p.x - last.x) < HOVER_CLIENT_MOVE_EPS_PX &&
        Math.abs(p.y - last.y) < HOVER_CLIENT_MOVE_EPS_PX
      ) {
        return
      }
      lastProcessedClientRef.current = { x: p.x, y: p.y }
      runHitTest(p.x, p.y)
    }

    const onMove = (e: MouseEvent) => {
      pendingClientRef.current = { x: e.clientX, y: e.clientY }
      if (hoverRafRef.current != null) return
      hoverRafRef.current = requestAnimationFrame(() => {
        hoverRafRef.current = null
        flushHover()
      })
    }
    const onLeave = () => {
      pendingClientRef.current = null
      lastProcessedClientRef.current = null
      if (hoverRafRef.current != null) {
        cancelAnimationFrame(hoverRafRef.current)
        hoverRafRef.current = null
      }
      setHoveredNodeId(null)
      setHoveredWaypointId(null)
    }
    el.addEventListener('mousemove', onMove)
    el.addEventListener('mouseleave', onLeave)
    return () => {
      if (hoverRafRef.current != null) cancelAnimationFrame(hoverRafRef.current)
      hoverRafRef.current = null
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
    }
  }, [domNode, size.width, size.height, planetGrid, waypointGrid])

  useEffect(() => {
    const el = domNode
    if (!el || !planetGrid) return

    const onClick = (e: MouseEvent) => {
      if (e.button !== 0) return
      const t = transformRef.current
      if (!t) return
      const paneRect = el.getBoundingClientRect()
      const flow = clientToFlowPosition(e.clientX, e.clientY, el, t, paneRect)
      if (!flow) return
      const rawScale = t[2]
      const scale = safeZoomScale(rawScale)
      const radiusPlanet = PLANET_LABEL_HOVER_RADIUS_PX / scale
      const { px, py } = flowCenterToPlanet(flow.x, flow.y)
      const closestId = findClosestPlanetWithinRadius(planetGrid, px, py, radiusPlanet)
      if (closestId == null) {
        if (pinnedNodeIdRef.current != null) {
          setPinnedNodeId(null)
        }
        return
      }
      if (!showAnyLabelOption) {
        if (pinnedNodeIdRef.current != null) {
          setPinnedNodeId(null)
        }
        return
      }
      setPinnedNodeId((prev) => {
        if (prev === closestId) return null
        return closestId
      })
    }
    el.addEventListener('click', onClick)
    return () => el.removeEventListener('click', onClick)
  }, [domNode, planetGrid, showAnyLabelOption])

  if (!transform || size.width <= 0 || size.height <= 0) return null
  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  const hoveredForDisplay = planetGrid ? hoveredNodeId : null

  const LABEL_OFFSET_X_PX = 9
  const LABEL_OFFSET_Y_PX = -12

  /**
   * Dots and labels must not share one per-planet stacking group: later planets' dots were painting
   * above earlier planets' labels (same z-index, DOM order), which looked like map bleed-through.
   */
  return (
    <div
      className="pointer-events-none absolute inset-0 z-[5]"
      aria-hidden={pinnedNodeId == null ? true : undefined}
    >
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
          if (hoveredWaypointIdForLabel !== w.id) return null
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
        {mapNodes.map((mapNode) => {
          const { cx, cy } = flowCenterFromMapNode(mapNode)
          const paneX = cx * scale + tx
          const paneY = cy * scale + ty
          const labelSrc = labelSourceByNodeId.get(mapNode.id)
          const coordX =
            labelSrc != null && Number.isFinite(labelSrc.mapX) ? labelSrc.mapX : Number(mapNode.x)
          const coordY =
            labelSrc != null && Number.isFinite(labelSrc.mapY) ? labelSrc.mapY : Number(mapNode.y)
          const isPinned = pinnedNodeId === mapNode.id
          const showHoverLabel =
            pinnedNodeId == null && showAnyLabelOption && hoveredForDisplay === mapNode.id
          const showLabel = isPinned || showHoverLabel
          if (!showLabel) return null
          return (
            <div
              key={`label-${mapNode.id}`}
              className={cn(
                'absolute font-mono text-gray-300',
                isPinned && 'pointer-events-auto z-[2]'
              )}
              style={{
                left: Math.round(paneX - DOT_PIXELS / 2 + LABEL_OFFSET_X_PX),
                top: Math.round(paneY - DOT_PIXELS / 2 + LABEL_OFFSET_Y_PX),
                fontSize: 10,
                backgroundColor: '#000000',
                borderRadius: 6,
              }}
              onClick={isPinned ? (e) => e.stopPropagation() : undefined}
            >
              <PlanetMapLabel
                options={planetLabelOptions}
                nodeId={mapNode.id}
                planet={labelSrc?.planet}
                ownerName={labelSrc?.ownerName}
                planetX={coordX}
                planetY={coordY}
              />
            </div>
          )
        })}
      </div>
    </div>
  )
}
