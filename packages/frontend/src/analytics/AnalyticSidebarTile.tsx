import { useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../lib/utils'
import { tileClassName } from './tileChrome'

/** Enable checkbox on every analytics-bar row. One class so the accent cannot drift. */
export const analyticEnableCheckboxClassName =
  'h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0'

/** Checkbox inside an analytics-bar details pane. One class so pane size and accent stay aligned. */
export const analyticDetailCheckboxClassName =
  'h-3.5 w-3.5 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0 disabled:opacity-50'

type AnalyticSidebarTileBase = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  /**
   * GameInfo inactivity. False greys the tile and disables the enable checkbox
   * even when the current view mode is supported.
   */
  available?: boolean
  /** Native title, used for inactivity hints. */
  hint?: string
}

type AnalyticSidebarTileProps = AnalyticSidebarTileBase &
  (
    | {
        children?: undefined
        detailsLabel?: undefined
      }
    | {
        children: ReactNode
        /** Accessible name: Expand/Collapse {detailsLabel}. */
        detailsLabel: string
      }
  )

/**
 * Shared analytics-bar row: enable checkbox, catalog name, and (when the
 * analytic has extra controls) a chevron pane. Subcontrols belong in
 * `children`, not beside the enable checkbox.
 */
export function AnalyticSidebarTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  available,
  hint,
  detailsLabel,
  children,
}: AnalyticSidebarTileProps) {
  const canToggle = supportsMode && (available ?? true)
  const hasDetails = children != null
  const detailsOpenable = hasDetails && canToggle && enabled
  const [expanded, setExpanded] = useState(false)
  const [prevDetailsOpenable, setPrevDetailsOpenable] = useState(detailsOpenable)
  if (detailsOpenable !== prevDetailsOpenable) {
    setPrevDetailsOpenable(detailsOpenable)
    if (!detailsOpenable) {
      setExpanded(false)
    }
  }

  const showBody = detailsOpenable && expanded

  return (
    <div
      title={hint}
      className={cn(
        tileClassName({ supportsMode: canToggle, depressed: depressed && canToggle }),
        'flex min-w-0 max-w-full flex-col'
      )}
    >
      <div className={cn('flex items-center gap-1 py-1.5 pl-2', hasDetails ? 'pr-0.5' : 'pr-2')}>
        <label
          className={cn(
            'flex min-w-0 flex-1 cursor-pointer items-center gap-2 py-0.5',
            !canToggle && 'cursor-default'
          )}
        >
          <input
            type="checkbox"
            checked={enabled}
            onChange={() => canToggle && onToggle()}
            disabled={!canToggle}
            className={analyticEnableCheckboxClassName}
          />
          <span className="min-w-0 truncate">{name}</span>
        </label>
        {hasDetails ? (
          <button
            type="button"
            aria-expanded={showBody}
            aria-label={showBody ? `Collapse ${detailsLabel}` : `Expand ${detailsLabel}`}
            disabled={!detailsOpenable}
            onClick={() => detailsOpenable && setExpanded((open) => !open)}
            className={cn(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded text-slate-400 transition-colors',
              detailsOpenable &&
                'hover:bg-black/15 hover:text-slate-200 focus-visible:outline focus-visible:ring-1 focus-visible:ring-slate-500',
              !detailsOpenable && 'cursor-default opacity-40'
            )}
          >
            <ChevronDown
              className={cn(
                'h-4 w-4 shrink-0 transition-transform duration-150',
                !showBody && '-rotate-90'
              )}
              aria-hidden
            />
          </button>
        ) : null}
      </div>
      {showBody ? (
        <div
          className="flex min-w-0 flex-col gap-1.5 border-t border-[#52575d]/70 px-2 pb-2 pt-1.5 text-xs text-slate-300"
          onClick={(event) => event.stopPropagation()}
        >
          {children}
        </div>
      ) : null}
    </div>
  )
}
