import { cn } from '../lib/utils'
import { tileClassName } from './tileChrome'

export type GenericAnalyticCheckboxProps = {
  name: string
  enabled: boolean
  supportsMode: boolean
  depressed: boolean
  onToggle: () => void
}

/** Default sidebar chrome: enable checkbox with no extra controls. */
export function GenericAnalyticCheckbox({
  name,
  enabled,
  supportsMode,
  depressed,
  onToggle,
}: GenericAnalyticCheckboxProps) {
  return (
    <label
      className={cn(
        'flex cursor-pointer items-center gap-2 px-2 py-1.5',
        tileClassName({ supportsMode, depressed })
      )}
    >
      <input
        type="checkbox"
        checked={enabled}
        onChange={() => supportsMode && onToggle()}
        disabled={!supportsMode}
        className="h-4 w-4 shrink-0 rounded border-[#52575d] bg-slate-700 text-slate-200 accent-slate-400 focus:ring-[#52575d] focus:ring-offset-0"
      />
      <span className="min-w-0 truncate">{name}</span>
    </label>
  )
}
