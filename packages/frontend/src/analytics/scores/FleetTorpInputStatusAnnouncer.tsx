import { useEffect, useRef, useState } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail } from '../../api/bff'
import { analyticScopeKey } from '../../lib/analyticScopeKey'
import {
  aggregateFleetTorpInputStatusForScope,
  fleetTorpInputAnnouncementForTransition,
  type FleetTorpInputStatus,
} from './fleetTorpInputStatus'

type FleetTorpInputStatusAnnouncerProps = {
  analyticScope: AnalyticShellScope
  inferenceByRow: ScoresInferenceRowDetail[]
}

export function FleetTorpInputStatusAnnouncer({
  analyticScope,
  inferenceByRow,
}: FleetTorpInputStatusAnnouncerProps) {
  const previousStatusesRef = useRef<Map<string, FleetTorpInputStatus | null>>(new Map())
  const [announcement, setAnnouncement] = useState('')

  useEffect(() => {
    const scopeKey = analyticScopeKey(analyticScope)
    const nextStatus = aggregateFleetTorpInputStatusForScope(inferenceByRow)
    const previousStatus = previousStatusesRef.current.get(scopeKey) ?? null
    const text =
      nextStatus != null
        ? fleetTorpInputAnnouncementForTransition(previousStatus, nextStatus)
        : null
    previousStatusesRef.current.set(scopeKey, nextStatus)

    if (text == null) {
      return
    }

    setAnnouncement('')
    const frameId = requestAnimationFrame(() => {
      setAnnouncement(text)
    })
    return () => cancelAnimationFrame(frameId)
  }, [analyticScope, inferenceByRow])

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="true"
      className="sr-only"
    >
      {announcement}
    </div>
  )
}
