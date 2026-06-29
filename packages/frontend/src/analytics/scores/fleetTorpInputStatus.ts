import type { ScoresInferenceRowDetail } from '../../api/bff'
import type { FleetTorpInputStatus } from '../../api/inferenceStreamEventSchema'
import { FLEET_TORP_INPUT_STATUSES } from '../../api/inferenceStreamEventSchema'
import { isRecord } from './scoresWireParsers'

export { FLEET_TORP_INPUT_STATUSES, type FleetTorpInputStatus }

export function parseFleetTorpInputStatus(value: unknown): FleetTorpInputStatus | null {
  if (
    typeof value === 'string' &&
    (FLEET_TORP_INPUT_STATUSES as readonly string[]).includes(value)
  ) {
    return value as FleetTorpInputStatus
  }
  return null
}

/** Diagnostics-only reader for debug panels; functional UI paths use detail first-class fields. */
export function readFleetTorpInputStatusFromDiagnostics(
  diagnostics: Record<string, unknown>
): FleetTorpInputStatus | null {
  return parseFleetTorpInputStatus(diagnostics.fleetTorpInputStatus)
}

type FleetTorpInputStatusPresentation = {
  showsTableIndicator: boolean
  appendsToInferenceAccessibleLabel: boolean
  announceOnEnterFrom: 'any' | 'pending_only' | 'never'
}

const FLEET_TORP_INPUT_STATUS_PRESENTATION: Record<
  FleetTorpInputStatus,
  FleetTorpInputStatusPresentation
> = {
  not_applicable: {
    showsTableIndicator: false,
    appendsToInferenceAccessibleLabel: false,
    announceOnEnterFrom: 'never',
  },
  pending: {
    showsTableIndicator: true,
    appendsToInferenceAccessibleLabel: true,
    announceOnEnterFrom: 'any',
  },
  applied: {
    showsTableIndicator: false,
    appendsToInferenceAccessibleLabel: true,
    announceOnEnterFrom: 'pending_only',
  },
  unavailable: {
    showsTableIndicator: true,
    appendsToInferenceAccessibleLabel: true,
    announceOnEnterFrom: 'any',
  },
}

export function fleetTorpInputAccessibleLabel(status: FleetTorpInputStatus): string {
  switch (status) {
    case 'not_applicable':
      return 'Prior-turn fleet torpedo overlay not applicable on turn 1'
    case 'pending':
      return 'Prior-turn fleet torpedo overlay pending; explanations may update when fleet data loads'
    case 'applied':
      return 'Prior-turn fleet torpedo overlay applied from persisted fleet snapshot'
    case 'unavailable':
      return 'Prior-turn fleet torpedo overlay unavailable'
  }
}

/** Diagnostics-only reader for debug panels; functional UI paths use detail first-class fields. */
export function readFleetTorpOverlayBeliefSetTorpIdsFromDiagnostics(
  diagnostics: Record<string, unknown>
): number[] | null {
  const overlay = diagnostics.fleetTorpOverlay
  if (!isRecord(overlay)) {
    return null
  }
  const ids = overlay.beliefSetTorpIds
  if (!Array.isArray(ids)) {
    return null
  }
  return ids.filter((id): id is number => typeof id === 'number')
}

export function fleetTorpInputShowsTableIndicator(status: FleetTorpInputStatus): boolean {
  return FLEET_TORP_INPUT_STATUS_PRESENTATION[status].showsTableIndicator
}

export function fleetTorpInputAppendsToInferenceAccessibleLabel(
  status: FleetTorpInputStatus
): boolean {
  return FLEET_TORP_INPUT_STATUS_PRESENTATION[status].appendsToInferenceAccessibleLabel
}

export function fleetTorpInputAnnouncementForTransition(
  previous: FleetTorpInputStatus | null,
  next: FleetTorpInputStatus
): string | null {
  if (previous === next) {
    return null
  }
  const { announceOnEnterFrom } = FLEET_TORP_INPUT_STATUS_PRESENTATION[next]
  if (announceOnEnterFrom === 'never') {
    return null
  }
  if (announceOnEnterFrom === 'pending_only' && previous !== 'pending') {
    return null
  }
  return fleetTorpInputAccessibleLabel(next)
}

export function readFleetTorpInputStatusFromDetail(
  detail: ScoresInferenceRowDetail
): FleetTorpInputStatus | null {
  return parseFleetTorpInputStatus(detail.fleetTorpInputStatus)
}

export function readFleetTorpOverlayBeliefSetTorpIdsFromDetail(
  detail: ScoresInferenceRowDetail
): number[] | null {
  const ids = detail.fleetTorpOverlayBeliefSetTorpIds
  if (ids == null) {
    return null
  }
  return ids.filter((id): id is number => typeof id === 'number')
}

export function countFleetTorpPendingRows(details: ScoresInferenceRowDetail[]): number {
  return details.filter(
    (detail) => readFleetTorpInputStatusFromDetail(detail) === 'pending'
  ).length
}

export function fleetTorpInputScopeBannerText(pendingCount: number): string | null {
  if (pendingCount <= 0) {
    return null
  }
  if (pendingCount === 1) {
    return 'Prior-turn fleet data is still loading for one player. Provisional build explanations may update when fleet@(N-1) is available.'
  }
  return `Prior-turn fleet data is still loading for ${pendingCount} players. Provisional build explanations may update when fleet@(N-1) is available.`
}
