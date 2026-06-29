import { useEffect, useRef, useState } from 'react'
import type { AnalyticShellScope, ScoresInferenceRowDetail } from '../../api/bff'
import { analyticScopeKey } from '../../lib/analyticScopeKey'
import {
  fleetTorpInputAnnouncementForTransition,
  readFleetTorpInputStatusFromDetail,
  type FleetTorpInputStatus,
} from './fleetTorpInputStatus'

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
        const text = fleetTorpInputAnnouncementForTransition(previousStatus, nextStatus)
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
