import { cn } from '../../lib/utils'

type InferenceSolutionCountBadgeProps = {
  count: number
  isSearching: boolean
  isIncomplete?: boolean
  label: string
  disabled?: boolean
  onClick?: () => void
  tone?: 'exact' | 'residual'
}

export function InferenceSolutionCountBadge({
  count,
  isSearching,
  isIncomplete = false,
  label,
  disabled = false,
  onClick,
  tone = 'exact',
}: InferenceSolutionCountBadgeProps) {
  const isResidual = tone === 'residual'
  const className = cn(
    'relative inline-flex h-6 min-w-6 items-center justify-center overflow-visible rounded px-1.5 text-xs font-medium border',
    isResidual ? 'text-sky-400 border-sky-500/70' : 'text-emerald-400 border-emerald-500/70',
    isIncomplete && 'border-dashed',
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
