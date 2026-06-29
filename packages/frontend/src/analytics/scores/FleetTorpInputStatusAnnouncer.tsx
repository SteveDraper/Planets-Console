import { useEffect, useRef, useState } from 'react'
import type { ScoresInferenceRowDetail } from '../../api/bff'
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

type FleetTorpInputStatusAnnouncerProps = {
  inferenceByRow: ScoresInferenceRowDetail[]
}

export function FleetTorpInputStatusAnnouncer({
  inferenceByRow,
}: FleetTorpInputStatusAnnouncerProps) {
  const previousStatusesRef = useRef<Map<number, FleetTorpInputStatus | null>>(new Map())
  const [announcement, setAnnouncement] = useState('')

  useEffect(() => {
    const announcements: string[] = []
    for (const detail of inferenceByRow) {
      const playerId = detail.playerId
      if (playerId == null) {
        continue
      }
      const nextStatus = readFleetTorpInputStatusFromDetail(detail)
      const previousStatus = previousStatusesRef.current.get(playerId) ?? null
      if (nextStatus != null) {
        const text = announcementForTransition(previousStatus, nextStatus)
        if (text != null) {
          announcements.push(text)
        }
        previousStatusesRef.current.set(playerId, nextStatus)
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
  }, [inferenceByRow])

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
