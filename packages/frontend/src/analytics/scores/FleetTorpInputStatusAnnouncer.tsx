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
  const [announcement, setAnnouncement] = useState({ text: '', sequence: 0 })

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

    // A new key per announcement remounts the text node, so the live region
    // announces again even when the text repeats.
    const frameId = requestAnimationFrame(() => {
      setAnnouncement((previous) => ({ text, sequence: previous.sequence + 1 }))
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
      <span key={announcement.sequence}>{announcement.text}</span>
    </div>
  )
}
