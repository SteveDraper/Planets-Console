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
  return status === 'pending' || status === 'unavailable'
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
