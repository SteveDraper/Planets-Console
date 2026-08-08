/**
 * Planet **map interaction contributor** (descriptive) + pin / waypoint paint state.
 */

import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useStore } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import {
  findClosestPlanetWithinRadius,
  flowCenterToPlanet,
  type PlanetSpatialGrid,
} from '../../lib/planetSpatialGrid'
import { clientToFlowPosition, safeZoomScale } from '../../lib/mapFlowGeometry'
import { PlanetMapLabel } from '../../components/PlanetMapLabel'
import {
  planetLabelOptionsShowAnyLabel,
  type PlanetLabelOptions,
} from '../../components/planetMapLabelModel'
import type { MapNodeLabelSource } from '../../components/map-graph/FixedSizeDotsOverlay'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import { useMapInteractionContributor } from '../useMapInteractionContributor'
import {
  mapHitContextFromState,
  useMapInteractionHitState,
} from '../mapInteractionRegistry'
import {
  hitTestPlanetAtPointer,
  hitTestWaypointAtPointer,
  PLANET_LABEL_HOVER_RADIUS_PX,
  resolvePinnedPlanet,
} from './planetHitTest'

export type PlanetMapPaintState = {
  hoveredWaypointId: string | null
}

const PlanetMapPaintContext = createContext<PlanetMapPaintState>({
  hoveredWaypointId: null,
})

export function usePlanetMapPaintState(): PlanetMapPaintState {
  return useContext(PlanetMapPaintContext)
}

type PlanetMapInteractionProps = {
  planetGrid: PlanetSpatialGrid | null
  planetLabelOptions: PlanetLabelOptions
  labelSourceByNodeId: Map<string, MapNodeLabelSource>
  mapNodes: CombinedMapData['nodes']
  waypointGrid: PlanetSpatialGrid | null
  children?: ReactNode
}

export function PlanetMapInteraction({
  planetGrid,
  planetLabelOptions,
  labelSourceByNodeId,
  mapNodes,
  waypointGrid,
  children,
}: PlanetMapInteractionProps) {
  const hitState = useMapInteractionHitState()
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [pinState, setPinState] = useState<{
    mapKey: string
    nodeId: string | null
  }>({ mapKey: '', nodeId: null })
  const pinnedNodeIdRef = useRef<string | null>(null)
  const transformRef = useRef(transform)
  useLayoutEffect(() => {
    transformRef.current = transform
  }, [transform])

  const showAnyLabelOption = planetLabelOptionsShowAnyLabel(planetLabelOptions)

  const mapNodeIdsKey = useMemo(() => mapNodes.map((n) => n.id).join('\0'), [mapNodes])
  const pinnedNodeId =
    showAnyLabelOption &&
    pinState.mapKey === mapNodeIdsKey &&
    pinState.nodeId != null &&
    mapNodes.some((n) => n.id === pinState.nodeId)
      ? pinState.nodeId
      : null

  useLayoutEffect(() => {
    pinnedNodeIdRef.current = pinnedNodeId
  }, [pinnedNodeId])

  useEffect(() => {
    if (pinnedNodeId == null) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setPinState({ mapKey: mapNodeIdsKey, nodeId: null })
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [pinnedNodeId, mapNodeIdsKey])

  // Pin toggle via pane click (hover-only surface; full click dispatch is #294).
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
      const scale = safeZoomScale(t[2])
      const radiusPlanet = PLANET_LABEL_HOVER_RADIUS_PX / scale
      const { px, py } = flowCenterToPlanet(flow.x, flow.y)
      const closestId = findClosestPlanetWithinRadius(
        planetGrid,
        px,
        py,
        radiusPlanet
      )
      if (closestId == null || !showAnyLabelOption) {
        if (pinnedNodeIdRef.current != null) {
          setPinState({ mapKey: mapNodeIdsKey, nodeId: null })
        }
        return
      }
      setPinState((prev) => {
        const current =
          prev.mapKey === mapNodeIdsKey ? prev.nodeId : null
        return {
          mapKey: mapNodeIdsKey,
          nodeId: current === closestId ? null : closestId,
        }
      })
    }
    el.addEventListener('click', onClick)
    return () => el.removeEventListener('click', onClick)
  }, [domNode, planetGrid, showAnyLabelOption, mapNodeIdsKey])

  const hit = mapHitContextFromState(hitState)

  const hoveredWaypointId = useMemo(() => {
    if (pinnedNodeId != null || hit == null) return null
    return hitTestWaypointAtPointer(hit, waypointGrid)
  }, [hit, pinnedNodeId, waypointGrid])

  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (!showAnyLabelOption && pinnedNodeId == null) return null

    const contributionFromHit = (
      planetHit: NonNullable<ReturnType<typeof resolvePinnedPlanet>>,
      pinned: boolean
    ) => ({
      id: `planet:${planetHit.nodeId}`,
      role: 'planet' as const,
      kind: 'descriptive' as const,
      title: 'Planet',
      placement: {
        mode: 'anchor' as const,
        flowX: planetHit.flowX,
        flowY: planetHit.flowY,
        pinned,
      },
      blocks: [
        {
          type: 'rich' as const,
          content: (
            <PlanetMapLabel
              options={planetLabelOptions}
              nodeId={planetHit.nodeId}
              planet={planetHit.labelSource?.planet}
              ownerName={planetHit.labelSource?.ownerName}
              planetX={planetHit.mapX}
              planetY={planetHit.mapY}
            />
          ),
        },
      ],
    })

    return {
      id: 'planet',
      role: 'planet',
      hitTest: (ctx) => {
        const pinned =
          pinnedNodeIdRef.current != null
            ? resolvePinnedPlanet(
                pinnedNodeIdRef.current,
                mapNodes,
                labelSourceByNodeId
              )
            : null
        const planetHit =
          pinned ??
          (showAnyLabelOption
            ? hitTestPlanetAtPointer(ctx, planetGrid, mapNodes, labelSourceByNodeId)
            : null)
        if (planetHit == null) return null
        return contributionFromHit(planetHit, pinned != null)
      },
      stickyContribution: () => {
        if (pinnedNodeIdRef.current == null) return null
        const pinned = resolvePinnedPlanet(
          pinnedNodeIdRef.current,
          mapNodes,
          labelSourceByNodeId
        )
        if (pinned == null) return null
        return contributionFromHit(pinned, true)
      },
    }
  }, [
    showAnyLabelOption,
    pinnedNodeId,
    mapNodes,
    labelSourceByNodeId,
    planetGrid,
    planetLabelOptions,
  ])

  useMapInteractionContributor(contributor)

  const paint = useMemo<PlanetMapPaintState>(
    () => ({ hoveredWaypointId }),
    [hoveredWaypointId]
  )

  return (
    <PlanetMapPaintContext.Provider value={paint}>
      {children}
    </PlanetMapPaintContext.Provider>
  )
}
