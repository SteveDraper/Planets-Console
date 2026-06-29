import { useEffect, useRef, useState } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail } from '../../api/bff'
import { analyticScopeKey } from '../../lib/analyticScopeKey'
import {
  fleetTorpInputAccessibleLabel,
  readFleetTorpInputStatusFromDetail,
  type FleetTorpInputStatus,
} from './fleetTorpInputStatus'

// Announce entering pending, applied (only from pending), or unavailable; other
// transitions (including not_applicable) are silent so table cells own steady-state labels.
function announcementForTransition(
  previous: FleetTorpInputStatus | null,
  next: FleetTorpInputStatus
): string | null {
  if (previous === next) {
    return null
  }
  if (next === 'applied' && previous === 'pending') {
    return fleetTorpInputAccessibleLabel('applied')
  }
  if (next === 'pending' && previous !== 'pending') {
    return fleetTorpInputAccessibleLabel('pending')
  }
  if (next === 'unavailable' && previous !== 'unavailable') {
    return fleetTorpInputAccessibleLabel('unavailable')
  }
  return null
}

function transitionKey(scope: AnalyticShellScope, playerId: number): string {
  return `${analyticScopeKey(scope)}:${playerId}`
}

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
    const announcements: string[] = []
    for (const detail of inferenceByRow) {
      const playerId = detail.playerId
      if (playerId == null) {
        continue
      }
      const nextStatus = readFleetTorpInputStatusFromDetail(detail)
      const key = transitionKey(analyticScope, playerId)
      const previousStatus = previousStatusesRef.current.get(key) ?? null
      if (nextStatus != null) {
        const text = announcementForTransition(previousStatus, nextStatus)
        if (text != null) {
          announcements.push(text)
        }
        previousStatusesRef.current.set(key, nextStatus)
      }
    }

    if (announcements.length === 0) {
      return
    }

    const text = announcements.join(' ')
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
