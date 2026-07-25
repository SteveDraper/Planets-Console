import { cn } from '../../lib/utils'
import { tileClassName } from '../tileChrome'
import { homeworldInactiveHint } from './constants'

type HomeworldLocatorTileProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
  /** When set, catalog is greyed and toggle is disabled (no traditional homeworlds). */
  inactiveReason: string | null
}

/**
 * Sidebar enable toggle for Homeworld locator.
 * Greys + hints when GameInfo settings make the analytic unavailable.
 */
export function HomeworldLocatorTile({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
  inactiveReason,
}: HomeworldLocatorTileProps) {
  const available = inactiveReason == null
  const canToggle = supportsMode && available
  const showAsUnsupported = !canToggle
  const hint = available ? undefined : homeworldInactiveHint(inactiveReason)

  return (
    <li className="min-w-0">
      <label
        title={hint}
        className={cn(
          'flex cursor-pointer items-center gap-2 px-2 py-1.5',
          tileClassName({
            supportsMode: !showAsUnsupported,
            depressed: depressed && canToggle,
          }),
          showAsUnsupported && 'cursor-default'
        )}
      >
        <input
          type="checkbox"
          checked={enabled}
          onChange={() => canToggle && onToggle()}
          disabled={!canToggle}
          className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
        />
        <span className="min-w-0 truncate">{name}</span>
      </label>
    </li>
  )
}
