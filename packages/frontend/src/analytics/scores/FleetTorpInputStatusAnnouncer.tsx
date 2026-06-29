import { useEffect, useRef, useState } from 'react'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import {
  fleetTorpInputAccessibleLabel,
  readFleetTorpInputStatusFromDetail,
  type FleetTorpInputStatus,
} from './fleetTorpInputStatus'

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
    for (const [index, detail] of inferenceByRow.entries()) {
      const playerId = detail.playerId ?? index
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

    if (announcements.length > 0) {
      setAnnouncement(announcements.join(' '))
    }
  }, [inferenceByRow])

  if (announcement.length === 0) {
    return null
  }

  return (
    <div className="sr-only" aria-live="polite" aria-atomic="true">
      {announcement}
    </div>
  )
}
