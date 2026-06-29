import type { ScoresInferenceRowDetail } from '../../api/bff'
import { isRecord } from './scoresWireParsers'

export const FLEET_TORP_INPUT_STATUSES = [
  'not_applicable',
  'pending',
  'applied',
  'unavailable',
] as const

export type FleetTorpInputStatus = (typeof FLEET_TORP_INPUT_STATUSES)[number]

export function readFleetTorpInputStatus(
  diagnostics: Record<string, unknown>
): FleetTorpInputStatus | null {
  const value = diagnostics.fleetTorpInputStatus
  if (
    typeof value === 'string' &&
    (FLEET_TORP_INPUT_STATUSES as readonly string[]).includes(value)
  ) {
    return value as FleetTorpInputStatus
  }
  return null
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

export function readFleetTorpOverlayBeliefSetTorpIds(
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
  const diagnostics = isRecord(detail.diagnostics) ? detail.diagnostics : {}
  return readFleetTorpInputStatus(diagnostics)
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
