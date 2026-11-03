import type { ReactNode } from 'react'
import { AnalyticFreshnessLabel } from '../AnalyticFreshnessLabel'
import type { AnalyticFreshness } from '../analyticFreshness'
import { FleetTorpInputStatusIndicator } from './FleetTorpInputStatusIndicator'
import {
  fleetTorpInputShowsTableIndicator,
  type FleetTorpInputStatus,
} from './fleetTorpInputStatus'

type InferenceCellChromeProps = {
  children: ReactNode
  fleetTorpStatus: FleetTorpInputStatus | null
  hullCatalogButton: ReactNode
  freshness?: AnalyticFreshness
}

export function InferenceCellChrome({
  children,
  fleetTorpStatus,
  hullCatalogButton,
  freshness = 'none',
}: InferenceCellChromeProps) {
  const showInferenceStatus = freshness !== 'turn-load'
  return (
    <div className="inline-flex items-center gap-1">
      <AnalyticFreshnessLabel freshness={freshness} />
      {showInferenceStatus ? children : null}
      {showInferenceStatus &&
      fleetTorpStatus != null &&
      fleetTorpInputShowsTableIndicator(fleetTorpStatus) ? (
        <FleetTorpInputStatusIndicator status={fleetTorpStatus} />
      ) : null}
      {hullCatalogButton}
    </div>
  )
}
