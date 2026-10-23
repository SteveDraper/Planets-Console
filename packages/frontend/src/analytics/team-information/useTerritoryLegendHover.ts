import { useEffect, useState } from 'react'
import type { HoveredTerritory, TerritoryPartition } from './kinds'
import { useTeamInformationHighlightStore } from '../../stores/teamInformationHighlight'

function isTerritoryPartition(value: string | undefined): value is TerritoryPartition {
  return value === 'player' || value === 'team'
}

function hoveredTerritoryFromTarget(target: EventTarget | null): HoveredTerritory | null {
  if (!(target instanceof Element)) return null
  const hover = target.closest('[data-territory-hover]')
  if (!(hover instanceof HTMLElement)) return null
  const partition = hover.dataset.territoryPartition
  const id = Number(hover.dataset.territoryId)
  if (!isTerritoryPartition(partition) || !Number.isInteger(id)) return null
  return { partition, id }
}

function isSameHoveredTerritory(
  left: HoveredTerritory | null,
  right: HoveredTerritory | null
): boolean {
  if (left === right) return true
  if (left == null || right == null) return false
  return left.partition === right.partition && left.id === right.id
}

function scrollableAncestor(node: HTMLElement): HTMLElement | null {
  let current = node.parentElement
  while (current != null) {
    const overflowY = getComputedStyle(current).overflowY
    if (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay') return current
    current = current.parentElement
  }
  return null
}

/**
 * Pointer movement over a legend name or color chip writes the highlight.
 * Leaving the list, or scrolling the nearest scrollport, clears it.
 * After a scroll the highlight stays clear until the pointer moves onto a name or color chip again.
 */
export function useTerritoryLegendHover(
  active: boolean
): (legend: HTMLUListElement | null) => void {
  const [legend, setLegend] = useState<HTMLUListElement | null>(null)
  const setHoveredTerritory = useTeamInformationHighlightStore((s) => s.setHoveredTerritory)

  useEffect(() => {
    if (!active || legend == null) return
    const scroller = scrollableAncestor(legend)

    const writeHoveredTerritory = (next: HoveredTerritory | null) => {
      const current = useTeamInformationHighlightStore.getState().hoveredTerritory
      if (isSameHoveredTerritory(current, next)) return
      setHoveredTerritory(next)
    }

    const onPointerMove = (event: PointerEvent) => {
      writeHoveredTerritory(hoveredTerritoryFromTarget(event.target))
    }
    const onPointerLeave = () => {
      writeHoveredTerritory(null)
    }
    const onScroll = () => {
      writeHoveredTerritory(null)
    }

    legend.addEventListener('pointermove', onPointerMove)
    legend.addEventListener('pointerleave', onPointerLeave)
    scroller?.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      legend.removeEventListener('pointermove', onPointerMove)
      legend.removeEventListener('pointerleave', onPointerLeave)
      scroller?.removeEventListener('scroll', onScroll)
    }
  }, [active, legend, setHoveredTerritory])

  return setLegend
}
