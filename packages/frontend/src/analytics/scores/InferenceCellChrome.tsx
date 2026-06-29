import type { ReactNode } from 'react'
import { FleetTorpInputStatusIndicator } from './FleetTorpInputStatusIndicator'
import {
  fleetTorpInputShowsTableIndicator,
  type FleetTorpInputStatus,
} from './fleetTorpInputStatus'

type InferenceCellChromeProps = {
  children: ReactNode
  fleetTorpStatus: FleetTorpInputStatus | null
  hullCatalogButton: ReactNode
}

export function InferenceCellChrome({
  children,
  fleetTorpStatus,
  hullCatalogButton,
}: InferenceCellChromeProps) {
  return (
    <div className="inline-flex items-center gap-1">
      {children}
      {fleetTorpStatus != null && fleetTorpInputShowsTableIndicator(fleetTorpStatus) ? (
        <FleetTorpInputStatusIndicator status={fleetTorpStatus} />
      ) : null}
      {hullCatalogButton}
    </div>
  )
}
