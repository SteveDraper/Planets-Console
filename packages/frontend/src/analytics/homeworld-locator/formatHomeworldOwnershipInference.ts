/**
 * Ownership inference hover copy from structured possible-owner facts.
 * Core emits kind tags + counts + winning strength; English templates live here
 * (ADR 0008).
 */

import type {
  MapRegionPossibleOwner,
  OwnershipWinningStrength,
} from '../../api/mapRegionOverlayTypes'
import { PROVENANCE_KIND_ASSERTED } from './constants'

/** Core machine kind for ship travel-envelope ownership evidence. */
export const PROVENANCE_KIND_SHIP_TRAVEL_ENVELOPE = 'ship_travel_envelope'

/** Core machine kind for nearby planetary ownership sightings. */
export const PROVENANCE_KIND_NEARBY_PLANET_OWNERSHIP = 'nearby_planet_ownership'

/** Core machine kind for preferred-candidate planetary ownership sightings. */
export const PROVENANCE_KIND_PREFERRED_CANDIDATE_OWNERSHIP =
  'preferred_candidate_ownership'

export type OwnershipInferenceEvidence = Pick<
  MapRegionPossibleOwner,
  'provenanceKinds' | 'provenanceKindCounts'
>

export type FormatOwnershipInferenceOptions = {
  /** Overlay ``ownershipWinningStrength`` after overlay projection. */
  winningStrength?: OwnershipWinningStrength | null
  /**
   * When true (default), missing ``winningStrength`` maps ship_travel_envelope
   * to definite (legacy unique-owner wires without the field). Pass false for
   * ambiguous multi-owner contenders so ship evidence cannot contradict
   * sector ambiguity.
   */
  allowLegacyShipDefinite?: boolean
}

/**
 * Sector ``ownershipWinningStrength`` applies only when the projected owner set
 * is unique (design §4.3.2). Ambiguous contenders must not inherit a sector max.
 */
export function uniqueOwnershipWinningStrength(
  possibleOwners: readonly unknown[] | undefined,
  ownershipWinningStrength: OwnershipWinningStrength | null | undefined
): OwnershipWinningStrength | undefined {
  if ((possibleOwners?.length ?? 0) !== 1) return undefined
  return ownershipWinningStrength ?? undefined
}

function observationCount(
  evidence: OwnershipInferenceEvidence,
  kind: string
): number {
  const counts = evidence.provenanceKindCounts
  if (counts != null && Object.keys(counts).length > 0) {
    return counts[kind] ?? 0
  }
  // Legacy wire: unique kinds only -- presence is at least one observation.
  return evidence.provenanceKinds.includes(kind) ? 1 : 0
}

/**
 * Ownership status label with ship/planet observation counts when evidence is
 * present. Asserted → ``asserted``; unique strong → ``definite``; weak →
 * ``inferred``.
 *
 * Returns null when there is no ownership evidence to summarize.
 */
export function formatHomeworldOwnershipInferenceSummary(
  evidence: OwnershipInferenceEvidence | null | undefined,
  options: FormatOwnershipInferenceOptions = {}
): string | null {
  if (evidence == null) return null
  if (evidence.provenanceKinds.length === 0) return null

  if (
    evidence.provenanceKinds.includes(PROVENANCE_KIND_ASSERTED) ||
    options.winningStrength === 'asserted'
  ) {
    return 'asserted'
  }

  const shipObservations = observationCount(
    evidence,
    PROVENANCE_KIND_SHIP_TRAVEL_ENVELOPE
  )
  const planetObservations =
    observationCount(evidence, PROVENANCE_KIND_NEARBY_PLANET_OWNERSHIP) +
    observationCount(evidence, PROVENANCE_KIND_PREFERRED_CANDIDATE_OWNERSHIP)

  // Prefer Core-emitted ownershipWinningStrength (ADR 0010) for definite vs
  // inferred. Kind tags / counts are for observation tallies only -- do not
  // re-derive strength from kinds when winningStrength is present.
  let status: 'definite' | 'inferred'
  if (options.winningStrength != null) {
    status = options.winningStrength === 'strong' ? 'definite' : 'inferred'
  } else if (
    (options.allowLegacyShipDefinite ?? true) &&
    evidence.provenanceKinds.includes(PROVENANCE_KIND_SHIP_TRAVEL_ENVELOPE)
  ) {
    // Legacy unique-owner wire without ownershipWinningStrength: ship envelope
    // maps to Core strong (ownership_provenance_strength).
    status = 'definite'
  } else {
    status = 'inferred'
  }

  return (
    `${status} (ship observations: ${shipObservations}, ` +
    `planet observations: ${planetObservations})`
  )
}

/**
 * Pick the ownership-evidence member that applies to a candidate row:
 * matching perspective slot, else the unique sector owner, else null.
 */
export function resolveOwnershipEvidenceForCandidate(
  possibleOwners: readonly MapRegionPossibleOwner[] | undefined,
  perspective: number | null
): MapRegionPossibleOwner | null {
  const owners = possibleOwners ?? []
  if (owners.length === 0) return null
  if (perspective != null) {
    const matched = owners.find((owner) => owner.ownerSlot === perspective)
    if (matched != null) return matched
  }
  if (owners.length === 1) return owners[0]!
  return null
}
