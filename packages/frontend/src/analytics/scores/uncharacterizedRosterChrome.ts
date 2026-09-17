import type { ScoresInferenceRowDetail } from '../../api/bff'
import {
  latticeSignatureSchema,
  placeholderDepartureSchema,
  unknownLossLeftoverSchema,
  type LatticeSignature,
  type PlaceholderDeparture,
  type UnknownLossLeftover,
} from '../../api/inferenceStreamEventSchema'
import { militaryChangeFromDelta2x } from './inferenceConstraints'

export const UNCHARACTERIZED_ROSTER_DEFAULT_SUMMARY = 'Uncharacterized roster'
export const UNKNOWN_LOSS_SHIP_CONTRIBUTION_PHRASE =
  'Includes unknown lost-ship contribution'

const UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID = 'unknown_military_ship'
const GENERIC_FREIGHTER_COMBO_ID = 'combo_freighter'

export function readUnknownLossLeftover(value: unknown): UnknownLossLeftover | null {
  const parsed = unknownLossLeftoverSchema.safeParse(value)
  return parsed.success ? parsed.data : null
}

export function readPlaceholderDeparture(value: unknown): PlaceholderDeparture | null {
  const parsed = placeholderDepartureSchema.safeParse(value)
  return parsed.success ? parsed.data : null
}

export function readLatticeSignature(value: unknown): LatticeSignature | null {
  const parsed = latticeSignatureSchema.safeParse(value)
  return parsed.success ? parsed.data : null
}

export function leftoverFromInferenceDetail(
  detail: ScoresInferenceRowDetail
): UnknownLossLeftover | null {
  return readUnknownLossLeftover(detail.leftover)
}

export function placeholderDeparturesFromDetail(
  detail: ScoresInferenceRowDetail
): PlaceholderDeparture[] {
  const departures: PlaceholderDeparture[] = []
  for (const entry of detail.placeholders ?? []) {
    const parsed = readPlaceholderDeparture(entry)
    if (parsed != null) {
      departures.push(parsed)
    }
  }
  return departures
}

export function latticeSignaturesFromDetail(detail: ScoresInferenceRowDetail): LatticeSignature[] {
  const signatures: LatticeSignature[] = []
  for (const entry of detail.latticeSignatures ?? []) {
    const parsed = readLatticeSignature(entry)
    if (parsed != null) {
      signatures.push(parsed)
    }
  }
  return signatures
}

/** Bound leftover is never a bare point number, including a 0 bound. */
export function formatUnknownLossLeftoverCell(leftover: UnknownLossLeftover): string {
  if (leftover.kind === 'unknown_loss_bound') {
    return `≥${militaryChangeFromDelta2x(leftover.lowerBound2x)}`
  }
  return String(militaryChangeFromDelta2x(leftover.unexplainedMilitaryDelta2x))
}

export function formatUnknownLossLeftoverModal(leftover: UnknownLossLeftover): string {
  if (leftover.kind === 'unknown_loss_bound') {
    return (
      `Military leftover at least ${militaryChangeFromDelta2x(leftover.lowerBound2x)}. ` +
      `${UNKNOWN_LOSS_SHIP_CONTRIBUTION_PHRASE}.`
    )
  }
  return `Military leftover ${militaryChangeFromDelta2x(leftover.unexplainedMilitaryDelta2x)}.`
}

export function uncharacterizedRosterAccessibleLabel(detail: ScoresInferenceRowDetail): string {
  const summary = detail.summary.trim() || UNCHARACTERIZED_ROSTER_DEFAULT_SUMMARY
  const leftover = leftoverFromInferenceDetail(detail)
  if (leftover?.kind === 'unknown_loss_bound') {
    return (
      `${summary}. Military leftover at least ${militaryChangeFromDelta2x(leftover.lowerBound2x)}. ` +
      `${UNKNOWN_LOSS_SHIP_CONTRIBUTION_PHRASE}.`
    )
  }
  if (leftover?.kind === 'point') {
    return `${summary}. Military leftover ${militaryChangeFromDelta2x(leftover.unexplainedMilitaryDelta2x)}.`
  }
  return summary
}

export function shipClassLabel(shipClass: PlaceholderDeparture['shipClass']): string {
  return shipClass === 'warship' ? 'Warship' : 'Freighter'
}

export function shipClassCountLabel(
  shipClass: PlaceholderDeparture['shipClass'],
  count: number
): string {
  const noun =
    shipClass === 'warship'
      ? count === 1
        ? 'warship'
        : 'warships'
      : count === 1
        ? 'freighter'
        : 'freighters'
  return `${count} ${noun}`
}

export function formatPlaceholderDepartureLabel(departure: PlaceholderDeparture): string {
  const countLabel = `${shipClassCountLabel(departure.shipClass, departure.count)} departed`
  if (departure.counterpartyPlayerId == null) {
    return countLabel
  }
  return `${countLabel} (counterparty player ${departure.counterpartyPlayerId})`
}

export function formatLatticeBuildLabel(build: LatticeSignature['build']): string {
  if (build.id === UNKNOWN_MILITARY_SHIP_PLACEHOLDER_ID) {
    return `Unknown military ship (${build.count})`
  }
  if (build.id === GENERIC_FREIGHTER_COMBO_ID) {
    return `Generic freighter (${build.count})`
  }
  return `${build.id} (${build.count})`
}
