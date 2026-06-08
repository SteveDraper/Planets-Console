import { cn } from '../../lib/utils'

type InferenceSolutionCountBadgeProps = {
  count: number
  isSearching: boolean
  isIncomplete?: boolean
  label: string
  disabled?: boolean
  onClick?: () => void
}

export function InferenceSolutionCountBadge({
  count,
  isSearching,
  isIncomplete = false,
  label,
  disabled = false,
  onClick,
}: InferenceSolutionCountBadgeProps) {
  const className = cn(
    'relative inline-flex h-6 min-w-6 items-center justify-center overflow-visible rounded px-1.5 text-xs font-medium text-emerald-400',
    isIncomplete ? 'border border-dashed border-emerald-500/70' : 'border border-emerald-500/70',
    !disabled && onClick != null && 'hover:bg-white/10',
    disabled && 'cursor-default opacity-60',
    isSearching && 'inference-solution-count-searching'
  )

  const content = (
    <>
      {isSearching ? <span className="inference-border-dot" aria-hidden /> : null}
      {count}
    </>
  )

  if (onClick != null) {
    return (
      <button
        type="button"
        title={label}
        aria-label={label}
        disabled={disabled}
        onClick={disabled ? undefined : onClick}
        className={className}
      >
        {content}
      </button>
    )
  }

  return (
    <span title={label} aria-label={label} className={className}>
      {content}
    </span>
  )
}
