import { useCallback, useEffect, useRef } from 'react'
import type { HoveredTerritory, TerritoryPartition } from './kinds'
import { useTeamInformationHighlightStore } from '../../stores/teamInformationHighlight'

/** Wait until the analytics bar stops moving before applying the legend hover. */
const SCROLL_SETTLE_MS = 120

function scrollableAncestor(node: HTMLElement): HTMLElement | null {
  let current = node.parentElement
  while (current != null) {
    const overflowY = getComputedStyle(current).overflowY
    if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') return current
    current = current.parentElement
  }
  return null
}

function hoveredTerritoryFromPoint(x: number, y: number): HoveredTerritory | null {
  const hit = document.elementFromPoint(x, y)
  const target = hit instanceof Element ? hit.closest('[data-territory-hover]') : null
  if (!(target instanceof HTMLElement)) return null
  const partition = target.dataset.territoryPartition
  const id = Number(target.dataset.territoryId)
  if ((partition !== 'player' && partition !== 'team') || !Number.isInteger(id)) return null
  return { partition: partition as TerritoryPartition, id }
}

/**
 * Legend hover for the name and color chip. While the nearest scrollport moves,
 * the highlight stays clear, then matches whatever chip or name is under the pointer.
 */
export function useTerritoryLegendHover(active: boolean) {
  const setHoveredTerritory = useTeamInformationHighlightStore((s) => s.setHoveredTerritory)
  const scrollingRef = useRef(false)
  const pointerRef = useRef<{ x: number; y: number } | null>(null)
  const setHoveredTerritoryRef = useRef(setHoveredTerritory)
  const legendRefCleanup = useRef<(() => void) | null>(null)
  setHoveredTerritoryRef.current = setHoveredTerritory

  useEffect(() => {
    if (!active) return
    const onPointerMove = (event: PointerEvent) => {
      pointerRef.current = { x: event.clientX, y: event.clientY }
    }
    document.addEventListener('pointermove', onPointerMove)
    return () => document.removeEventListener('pointermove', onPointerMove)
  }, [active])

  const legendRef = useCallback(
    (legend: HTMLUListElement | null) => {
      const previous = legendRefCleanup.current
      previous?.()
      legendRefCleanup.current = null
      if (!active || legend == null) return
      const scroller = scrollableAncestor(legend)
      if (scroller == null) return
      let settleTimer: ReturnType<typeof setTimeout> | undefined
      const onScroll = () => {
        scrollingRef.current = true
        setHoveredTerritoryRef.current(null)
        if (settleTimer != null) clearTimeout(settleTimer)
        settleTimer = setTimeout(() => {
          scrollingRef.current = false
          const pointer = pointerRef.current
          setHoveredTerritoryRef.current(
            pointer == null ? null : hoveredTerritoryFromPoint(pointer.x, pointer.y)
          )
        }, SCROLL_SETTLE_MS)
      }
      scroller.addEventListener('scroll', onScroll, { passive: true })
      legendRefCleanup.current = () => {
        scroller.removeEventListener('scroll', onScroll)
        if (settleTimer != null) clearTimeout(settleTimer)
        scrollingRef.current = false
      }
    },
    [active]
  )

  function legendHover(territory: HoveredTerritory) {
    return {
      onMouseEnter: () => {
        if (scrollingRef.current) return
        setHoveredTerritory(territory)
      },
      onMouseLeave: () => {
        if (scrollingRef.current) return
        setHoveredTerritory(null)
      },
    }
  }

  return { legendRef, legendHover }
}
