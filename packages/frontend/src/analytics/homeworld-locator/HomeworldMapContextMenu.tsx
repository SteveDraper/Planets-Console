/**
 * Map context menu for homeworld location/ownership asserts (#37).
 * Homeworld-owned: listens on the React Flow pane and hit-tests planets then sectors.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useStore } from '@xyflow/react'
import type { AnalyticShellScope, MapNode } from '../../api/bff'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import {
  findClosestPlanetWithinRadius,
  flowCenterToPlanet,
  type PlanetSpatialGrid,
} from '../../lib/planetSpatialGrid'
import { errorDetailFromUnknown } from '../../lib/queryRetry'
import { clientToFlowPosition, safeZoomScale } from '../../components/map-graph/geometry'
import { formatHomeworldOwnershipPickLabel } from './ownershipPickLabel'
import {
  findHomeworldSectorAtMapPoint,
  resolveOwnershipAssertTargetForPlanet,
  resolveOwnershipAssertTargetForSector,
  type OwnershipAssertTarget,
} from './resolveOwnershipAssertTarget'
import { parseHomeworldSectorIndex } from './homeworldSectorIndex'
import { useHomeworldLocatorAssertionMutation } from './useHomeworldLocatorMutations'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'

const PLANET_MENU_RADIUS_PX = 16

type MenuTarget =
  | {
      kind: 'planet'
      planetId: number
      ownership: OwnershipAssertTarget | null
      clientX: number
      clientY: number
    }
  | {
      kind: 'sector'
      sectorIndex: number
      ownership: OwnershipAssertTarget
      clientX: number
      clientY: number
    }

function planetIdFromNodeId(nodeId: string, nodes: readonly MapNode[]): number | null {
  const node = nodes.find((row) => row.id === nodeId)
  if (node?.planet?.id != null) {
    const raw = node.planet.id
    if (typeof raw === 'number' && Number.isFinite(raw)) return Math.trunc(raw)
    if (typeof raw === 'string' && raw.trim() !== '') {
      const parsed = Number.parseInt(raw.trim(), 10)
      if (Number.isFinite(parsed)) return parsed
    }
  }
  const localId = nodeId.includes(':') ? nodeId.slice(nodeId.indexOf(':') + 1) : nodeId
  const match = /^p(\d+)$/.exec(localId)
  if (match != null) return Number.parseInt(match[1]!, 10)
  return null
}

/** True when the event target is inside the open menu (or the menu itself). */
export function isEventInsideHomeworldMenu(
  target: EventTarget | null,
  menuElement: HTMLElement | null
): boolean {
  if (menuElement == null || !(target instanceof Node)) return false
  return menuElement.contains(target)
}

export type HomeworldMapContextMenuProps = {
  analyticScope: AnalyticShellScope | null
  enabled: boolean
  /** Unfiltered map overlays for ownership assert keying (not display-mode paint lists). */
  ownershipRegionOverlays: readonly MapRegionOverlay[]
  planetGrid: PlanetSpatialGrid | null
  planetMapNodes: readonly MapNode[]
  roster: readonly PerspectiveRow[]
}

export function HomeworldMapContextMenu({
  analyticScope,
  enabled,
  ownershipRegionOverlays,
  planetGrid,
  planetMapNodes,
  roster,
}: HomeworldMapContextMenuProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [menu, setMenu] = useState<MenuTarget | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const assertMutation = useHomeworldLocatorAssertionMutation(analyticScope)
  const setSelection = useHomeworldLocatorSelectionStore((s) => s.setSelection)

  const planetById = useMemo(() => {
    const map = new Map<number, MapNode>()
    for (const node of planetMapNodes) {
      const id = planetIdFromNodeId(node.id, [node])
      if (id != null) map.set(id, node)
    }
    return map
  }, [planetMapNodes])

  useEffect(() => {
    if (!enabled || domNode == null) return

    const onContextMenu = (event: MouseEvent) => {
      if (!transform) return
      const flow = clientToFlowPosition(event.clientX, event.clientY, domNode, transform)
      if (flow == null) {
        setMenu(null)
        return
      }
      const scale = safeZoomScale(transform[2])
      const { px, py } = flowCenterToPlanet(flow.x, flow.y)

      if (planetGrid != null) {
        const radiusPlanet = PLANET_MENU_RADIUS_PX / scale
        const closestId = findClosestPlanetWithinRadius(planetGrid, px, py, radiusPlanet)
        if (closestId != null) {
          const planetId = planetIdFromNodeId(closestId, planetMapNodes)
          if (planetId != null) {
            event.preventDefault()
            const node = planetById.get(planetId)
            const ownership =
              node != null
                ? resolveOwnershipAssertTargetForPlanet(
                    ownershipRegionOverlays,
                    planetId,
                    Number(node.x),
                    Number(node.y)
                  )
                : null
            setSelection({ kind: 'planet', planetId })
            setMenu({
              kind: 'planet',
              planetId,
              ownership,
              clientX: event.clientX,
              clientY: event.clientY,
            })
            return
          }
        }
      }

      const sector = findHomeworldSectorAtMapPoint(ownershipRegionOverlays, px, py)
      if (sector != null) {
        const ownership = resolveOwnershipAssertTargetForSector(sector)
        const sectorIndex = parseHomeworldSectorIndex(sector.id)
        if (ownership != null && sectorIndex != null) {
          event.preventDefault()
          setSelection({ kind: 'sector', sectorIndex })
          setMenu({
            kind: 'sector',
            sectorIndex,
            ownership,
            clientX: event.clientX,
            clientY: event.clientY,
          })
          return
        }
      }

      // Right-click on empty map space dismisses any open menu.
      setMenu(null)
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenu(null)
    }

    // Capture phase so React Flow pan/drag handlers cannot swallow the dismiss.
    const onPointerDownCapture = (event: PointerEvent) => {
      if (isEventInsideHomeworldMenu(event.target, menuRef.current)) return
      setMenu(null)
    }

    domNode.addEventListener('contextmenu', onContextMenu)
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('pointerdown', onPointerDownCapture, true)
    return () => {
      domNode.removeEventListener('contextmenu', onContextMenu)
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('pointerdown', onPointerDownCapture, true)
    }
  }, [
    enabled,
    domNode,
    transform,
    planetGrid,
    planetMapNodes,
    planetById,
    ownershipRegionOverlays,
    setSelection,
  ])

  if (!enabled || menu == null || analyticScope == null) return null

  const runOwnership = (action: 'upsert' | 'revoke', ownerSlot: number, target: OwnershipAssertTarget) => {
    assertMutation.mutate({
      axis: 'ownership',
      action,
      ownerSlot,
      planetId: target.keying === 'planet' ? target.planetId : (target.planetId ?? null),
      sectorIndex: target.keying === 'sector' ? target.sectorIndex : null,
    })
    setMenu(null)
  }

  return (
    <div
      ref={menuRef}
      className="fixed z-[80] min-w-[12rem] rounded border border-[#52575d] bg-[#2f3338] py-1 text-xs text-slate-100 shadow-lg"
      style={{ left: menu.clientX, top: menu.clientY }}
      role="menu"
    >
      {menu.kind === 'planet' ? (
        <>
          <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-slate-400">
            Planet {menu.planetId}
          </div>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left hover:bg-black/25 disabled:opacity-40"
            disabled={assertMutation.isPending}
            onClick={() => {
              assertMutation.mutate({
                axis: 'location',
                action: 'upsert',
                planetId: menu.planetId,
              })
              setMenu(null)
            }}
          >
            Assert as homeworld
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-1.5 text-left hover:bg-black/25 disabled:opacity-40"
            disabled={assertMutation.isPending}
            onClick={() => {
              assertMutation.mutate({
                axis: 'location',
                action: 'revoke',
                planetId: menu.planetId,
              })
              setMenu(null)
            }}
          >
            Revoke homeworld assert
          </button>
        </>
      ) : (
        <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-slate-400">
          Sector {menu.sectorIndex}
        </div>
      )}
      {menu.ownership != null && roster.length > 0 ? (
        <div className="mt-1 border-t border-[#52575d]/80 pt-1">
          <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-slate-400">
            Assert owner
          </div>
          {roster.map((player) => (
            <button
              key={player.playerId}
              type="button"
              role="menuitem"
              className="block w-full px-3 py-1.5 text-left hover:bg-black/25 disabled:opacity-40"
              disabled={assertMutation.isPending}
              onClick={() => runOwnership('upsert', player.ordinal, menu.ownership!)}
            >
              {formatHomeworldOwnershipPickLabel(player.name, player.raceName)}
            </button>
          ))}
        </div>
      ) : null}
      {assertMutation.error != null ? (
        <p className="max-w-[16rem] px-3 py-1 text-[10px] text-red-400 break-words" role="alert">
          {errorDetailFromUnknown(assertMutation.error)}
        </p>
      ) : null}
    </div>
  )
}
