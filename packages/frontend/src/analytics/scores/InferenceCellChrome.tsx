import type { ReactNode } from 'react'
import { FleetTorpInputStatusIndicator } from './FleetTorpInputStatusIndicator'
import type { FleetTorpInputStatus } from './fleetTorpInputStatus'

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
      {fleetTorpStatus != null ? (
        <FleetTorpInputStatusIndicator status={fleetTorpStatus} />
      ) : null}
      {hullCatalogButton}
    </div>
  )
}
