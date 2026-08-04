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
import { cn } from '../../lib/utils'
import { clientToFlowPosition, safeZoomScale } from '../../components/map-graph/geometry'
import { formatHomeworldOwnershipPickLabel } from './ownershipPickLabel'
import {
  findHomeworldSectorAtMapPoint,
  resolveOwnershipAssertTargetForPlanet,
  resolveOwnershipAssertTargetForSector,
  resolveOwnershipMenuSelectedSlots,
  resolveOwnershipRevokeSlots,
  type OwnershipAssertTarget,
} from './resolveOwnershipAssertTarget'
import { planetIdFromNodeId } from './planetIdFromMapNode'
import { parseHomeworldSectorIndex } from './homeworldSectorIndex'
import { buildOwnershipAssertionBody } from './ownershipAssertionBody'
import {
  isPlanetLocationAsserted,
  locationAssertMenuActions,
} from './homeworldMapMenuVisibility'
import {
  useHomeworldLocatorAssertionError,
  useHomeworldLocatorAssertionMutation,
  useHomeworldLocatorAssertionPending,
} from './useHomeworldLocatorMutations'
import { useHomeworldLocatorSelectionStore } from '../../stores/homeworldLocatorSelection'
import type { HomeworldMapMarker } from './wireSchema'

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

/** True when the event target is inside the open menu (or the menu itself). */
export function isEventInsideHomeworldMenu(
  target: EventTarget | null,
  menuElement: HTMLElement | null
): boolean {
  if (menuElement == null || !(target instanceof Node)) return false
  return menuElement.contains(target)
}

/**
 * Shared Owner submenu for planet and sector menus.
 * Roster picks upsert ownership; Unknown revokes asserted ownership for the target.
 * Current selection is bold: asserted owners, else a single inferred owner, else Unknown.
 */
function OwnerSubmenu({
  roster,
  disabled,
  selectedOwnerSlots,
  onPickOwner,
  onPickUnknown,
}: {
  roster: readonly PerspectiveRow[]
  disabled: boolean
  /** Asserted owner slots for this target; empty means Unknown is current. */
  selectedOwnerSlots: readonly number[]
  onPickOwner: (ownerSlot: number) => void
  onPickUnknown: () => void
}) {
  const [open, setOpen] = useState(false)
  const unknownSelected = selectedOwnerSlots.length === 0

  return (
    <div className="relative">
      <button
        type="button"
        role="menuitem"
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left hover:bg-black/25 disabled:opacity-40"
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <span>Owner</span>
        <span aria-hidden className="text-slate-400">
          ›
        </span>
      </button>
      {open ? (
        <div
          className="absolute left-full top-0 z-[81] ml-0.5 min-w-[12rem] rounded border border-[#52575d] bg-[#2f3338] py-1 shadow-lg"
          role="menu"
        >
          <button
            type="button"
            role="menuitem"
            aria-current={unknownSelected ? 'true' : undefined}
            className={cn(
              'block w-full px-3 py-1.5 text-left hover:bg-black/25 disabled:opacity-40',
              unknownSelected && 'font-bold'
            )}
            disabled={disabled}
            onClick={onPickUnknown}
          >
            Unknown
          </button>
          {roster.map((player) => {
            const selected = selectedOwnerSlots.includes(player.ordinal)
            return (
              <button
                key={player.playerId}
                type="button"
                role="menuitem"
                aria-current={selected ? 'true' : undefined}
                className={cn(
                  'block w-full px-3 py-1.5 text-left hover:bg-black/25 disabled:opacity-40',
                  selected && 'font-bold'
                )}
                disabled={disabled}
                onClick={() => onPickOwner(player.ordinal)}
              >
                {formatHomeworldOwnershipPickLabel(player.name, player.raceName)}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

export type HomeworldMapContextMenuProps = {
  analyticScope: AnalyticShellScope | null
  enabled: boolean
  /** Unfiltered map overlays for ownership assert keying (not display-mode paint lists). */
  ownershipRegionOverlays: readonly MapRegionOverlay[]
  homeworldMarkers: readonly HomeworldMapMarker[]
  planetGrid: PlanetSpatialGrid | null
  planetMapNodes: readonly MapNode[]
  roster: readonly PerspectiveRow[]
}

export function HomeworldMapContextMenu({
  analyticScope,
  enabled,
  ownershipRegionOverlays,
  homeworldMarkers,
  planetGrid,
  planetMapNodes,
  roster,
}: HomeworldMapContextMenuProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [menu, setMenu] = useState<MenuTarget | null>(null)
  const menuRef = useRef<HTMLDivElement | null>(null)
  const assertMutation = useHomeworldLocatorAssertionMutation(analyticScope)
  const assertPending = useHomeworldLocatorAssertionPending(analyticScope)
  const assertError = useHomeworldLocatorAssertionError(analyticScope)
  const setSelection = useHomeworldLocatorSelectionStore((s) => s.setSelection)
  const dismissMenuOnAssertSuccess = { onSuccess: () => setMenu(null) }

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

  const boundOwnerSlot =
    menu.kind === 'planet'
      ? (homeworldMarkers.find((marker) => marker.planetId === menu.planetId)?.perspective ??
        null)
      : null
  const unknownRevokeSlots =
    menu.ownership != null
      ? resolveOwnershipRevokeSlots(ownershipRegionOverlays, menu.ownership, {
          boundOwnerSlot,
        })
      : []
  const selectedOwnerSlots =
    menu.ownership != null
      ? resolveOwnershipMenuSelectedSlots(ownershipRegionOverlays, menu.ownership, {
          boundOwnerSlot,
        })
      : []

  const locationActions =
    menu.kind === 'planet'
      ? locationAssertMenuActions(
          isPlanetLocationAsserted(homeworldMarkers, menu.planetId)
        )
      : null

  const runOwnershipUpsert = (ownerSlot: number, target: OwnershipAssertTarget) => {
    assertMutation.mutate(
      buildOwnershipAssertionBody('upsert', ownerSlot, target),
      dismissMenuOnAssertSuccess
    )
  }

  const runOwnershipUnknown = async (target: OwnershipAssertTarget) => {
    // Clear asserted ownership for this target (planet: bound slot; sector: all asserted).
    for (const ownerSlot of unknownRevokeSlots) {
      await assertMutation.mutateAsync(buildOwnershipAssertionBody('revoke', ownerSlot, target))
    }
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
          {locationActions?.showAssertAsHomeworld ? (
            <button
              type="button"
              role="menuitem"
              className="block w-full px-3 py-1.5 text-left hover:bg-black/25 disabled:opacity-40"
              disabled={assertPending}
              onClick={() => {
                assertMutation.mutate(
                  {
                    axis: 'location',
                    action: 'upsert',
                    planetId: menu.planetId,
                  },
                  dismissMenuOnAssertSuccess
                )
              }}
            >
              Assert as homeworld
            </button>
          ) : null}
          {locationActions?.showRevokeHomeworldAssert ? (
            <button
              type="button"
              role="menuitem"
              className="block w-full px-3 py-1.5 text-left hover:bg-black/25 disabled:opacity-40"
              disabled={assertPending}
              onClick={() => {
                assertMutation.mutate(
                  {
                    axis: 'location',
                    action: 'revoke',
                    planetId: menu.planetId,
                  },
                  dismissMenuOnAssertSuccess
                )
              }}
            >
              Revoke homeworld assert
            </button>
          ) : null}
        </>
      ) : (
        <div className="px-3 py-1 text-[10px] uppercase tracking-wide text-slate-400">
          Sector {menu.sectorIndex}
        </div>
      )}
      {menu.ownership != null && roster.length > 0 ? (
        <div className="mt-1 border-t border-[#52575d]/80 pt-1">
          <OwnerSubmenu
            roster={roster}
            disabled={assertPending}
            selectedOwnerSlots={selectedOwnerSlots}
            onPickOwner={(ownerSlot) => runOwnershipUpsert(ownerSlot, menu.ownership!)}
            onPickUnknown={() => {
              void runOwnershipUnknown(menu.ownership!)
            }}
          />
        </div>
      ) : null}
      {assertError != null ? (
        <p className="max-w-[16rem] px-3 py-1 text-[10px] text-red-400 break-words" role="alert">
          {errorDetailFromUnknown(assertError)}
        </p>
      ) : null}
    </div>
  )
}
