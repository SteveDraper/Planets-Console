import { cn } from '../../lib/utils'
import {
  fleetTorpInputAccessibleLabel,
  readFleetTorpInputStatus,
  readFleetTorpOverlayBeliefSetTorpIds,
} from './fleetTorpInputStatus'

type FleetTorpInputStatusDetailProps = {
  diagnostics: Record<string, unknown>
  variant?: 'section' | 'inline'
  className?: string
}

export function FleetTorpInputStatusDetail({
  diagnostics,
  variant = 'section',
  className,
}: FleetTorpInputStatusDetailProps) {
  const status = readFleetTorpInputStatus(diagnostics)
  if (status == null) {
    return null
  }

  const label = fleetTorpInputAccessibleLabel(status)
  const beliefSetTorpIds =
    status === 'applied' ? readFleetTorpOverlayBeliefSetTorpIds(diagnostics) : null
  const beliefText =
    beliefSetTorpIds != null && beliefSetTorpIds.length > 0
      ? `Belief-set torpedo ids: ${beliefSetTorpIds.join(', ')}`
      : null

  if (variant === 'inline') {
    return (
      <p className={cn('mt-1 text-xs text-slate-400', className)}>
        {label}
        {beliefText != null ? ` · ${beliefText}` : ''}
      </p>
    )
  }

  return (
    <section className={cn('rounded border border-[#52575d]/70 bg-[#2a2d30] p-3', className)}>
      <h3 className="text-xs font-medium text-slate-200">Fleet torpedo overlay input</h3>
      <p className="mt-2 text-xs text-slate-300">{label}</p>
      {beliefText != null ? <p className="mt-1 text-xs text-slate-400">{beliefText}</p> : null}
    </section>
  )
}
