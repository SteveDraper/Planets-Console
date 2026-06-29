import { AlertTriangle, Ship } from 'lucide-react'
import { cn } from '../../lib/utils'
import {
  fleetTorpInputAccessibleLabel,
  fleetTorpInputShowsTableIndicator,
  type FleetTorpInputStatus,
} from './fleetTorpInputStatus'

type FleetTorpInputStatusIndicatorProps = {
  status: FleetTorpInputStatus
  className?: string
}

export function FleetTorpInputStatusIndicator({
  status,
  className,
}: FleetTorpInputStatusIndicatorProps) {
  if (!fleetTorpInputShowsTableIndicator(status)) {
    return null
  }

  const label = fleetTorpInputAccessibleLabel(status)
  const Icon = status === 'unavailable' ? AlertTriangle : Ship

  return (
    <span
      title={label}
      aria-hidden="true"
      className={cn(
        'inline-flex items-center justify-center rounded p-0.5',
        status === 'pending' ? 'text-amber-300/90' : 'text-slate-400',
        className
      )}
    >
      <Icon className="h-3.5 w-3.5" />
    </span>
  )
}
