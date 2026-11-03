import { cn } from '../lib/utils'
import type { AnalyticFreshness } from './analyticFreshness'

type FreshnessLabelCopy = {
  label: string
  title?: string
  className: string
}

/** Shown freshness. `none` has no row. Slate for turn load; amber matches the fleet count-discrepancy line. */
const FRESHNESS_LABEL: Record<Exclude<AnalyticFreshness, 'none'>, FreshnessLabelCopy> = {
  'turn-load': {
    label: 'Turn load',
    className: 'text-slate-400',
  },
  'provisional': {
    label: 'Provisional',
    title:
      'This is a saved answer from before a newer result for this player. It may change once that result is included. Backfill earlier turns updates turns you are not viewing. Otherwise a turn updates when you open it.',
    className: 'text-amber-300',
  },
}

type AnalyticFreshnessLabelProps = {
  freshness: AnalyticFreshness
  className?: string
}

export function AnalyticFreshnessLabel({
  freshness,
  className,
}: AnalyticFreshnessLabelProps) {
  if (freshness === 'none') {
    return null
  }
  const copy = FRESHNESS_LABEL[freshness]
  return (
    <span className={cn('text-xs', copy.className, className)} title={copy.title}>
      {copy.label}
    </span>
  )
}
