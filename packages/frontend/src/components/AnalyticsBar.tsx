import { useEffect, useRef } from 'react'
import { renderShellAnalyticSidebar } from '../analytics/renderShellAnalyticSidebar'
import type { AnalyticItem, AnalyticShellScope } from '../api/bff'

type ViewMode = 'tabular' | 'map'

type AnalyticsBarProps = {
  analytics: AnalyticItem[]
  enabledIds: Set<string>
  onToggle: (id: string) => void
  viewMode: ViewMode
  turnDataReady: boolean
  analyticScope: AnalyticShellScope | null
  reportShellError: (message: string) => void
}

/** Only analytics the user can toggle; base map is excluded from the pane. */
function selectableAnalytics(analytics: AnalyticItem[]): AnalyticItem[] {
  return analytics.filter((a) => a.type !== 'base')
}

function wheelDeltaY(event: WheelEvent, scroller: HTMLElement): number {
  if (event.deltaMode === WheelEvent.DOM_DELTA_LINE) return event.deltaY * 16
  if (event.deltaMode === WheelEvent.DOM_DELTA_PAGE) return event.deltaY * scroller.clientHeight
  return event.deltaY
}

function childConsumesWheel(scroller: HTMLElement, target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  let node: Element | null = target
  while (node && node !== scroller) {
    if (node instanceof HTMLElement) {
      const overflowY = getComputedStyle(node).overflowY
      const scrollsY = overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay'
      if (scrollsY && node.scrollHeight > node.clientHeight) return true
    }
    node = node.parentElement
  }
  return false
}

/**
 * Scroll the bar from the wheel. The listener is non-passive so preventDefault
 * can keep the gesture off the page when the bar itself can move.
 */
function scrollAnalyticsBarOnWheel(event: WheelEvent): void {
  if (event.ctrlKey) return
  const scroller = event.currentTarget
  if (!(scroller instanceof HTMLElement)) return
  if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return
  if (childConsumesWheel(scroller, event.target)) return
  if (scroller.scrollHeight <= scroller.clientHeight) return
  event.preventDefault()
  const maxScroll = scroller.scrollHeight - scroller.clientHeight
  const next = scroller.scrollTop + wheelDeltaY(event, scroller)
  scroller.scrollTop = Math.min(maxScroll, Math.max(0, next))
}

export function AnalyticsBar({
  analytics,
  enabledIds,
  onToggle,
  viewMode,
  turnDataReady,
  analyticScope,
  reportShellError,
}: AnalyticsBarProps) {
  const list = selectableAnalytics(analytics)
  const scrollerRef = useRef<HTMLElement>(null)
  useEffect(() => {
    const scroller = scrollerRef.current
    if (!scroller) return
    scroller.addEventListener('wheel', scrollAnalyticsBarOnWheel, { passive: false })
    return () => scroller.removeEventListener('wheel', scrollAnalyticsBarOnWheel)
  }, [])
  return (
    <aside
      ref={scrollerRef}
      className="flex h-full max-h-full min-h-0 w-full min-w-0 flex-col gap-0.5 overflow-x-clip overflow-y-auto border-r border-[#52575d] bg-[#40454a] p-2 text-slate-200"
    >
      <h2 className="px-2 py-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Analytics
      </h2>
      <ul className="flex flex-col gap-1.5">
        {list.map((a) => {
          const enabled = enabledIds.has(a.id)
          return (
            <li key={a.id} className="min-w-0">
              {renderShellAnalyticSidebar({
                viewMode,
                catalogItem: a,
                enabled,
                onToggle: () => onToggle(a.id),
                turnDataReady,
                analyticScope,
                reportShellError,
              })}
            </li>
          )
        })}
      </ul>
    </aside>
  )
}
