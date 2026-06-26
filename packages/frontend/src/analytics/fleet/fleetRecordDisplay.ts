import type {
  FleetBuildOptionSet,
  FleetFieldConstraint,
  FleetLastSeen,
  FleetTableRecord,
} from './fleetTableWireSchema'

export type FleetRecordFieldKey =
  | 'shipId'
  | 'hull'
  | 'engine'
  | 'beams'
  | 'launchers'
  | 'builtTurn'

type FleetBoundedFieldConstraint = Extract<FleetFieldConstraint, { kind: 'bounded' }>

const BOUNDED_OPERATOR_LABEL: Record<FleetBoundedFieldConstraint['operator'], string> =
  {
    lte: '<=',
    gte: '>=',
    lt: '<',
    gt: '>',
    eq: '=',
  }

/** Default consumer filter: active disposition rows only. */
export function activeFleetRecords(records: readonly FleetTableRecord[]): FleetTableRecord[] {
  return records.filter((record) => record.disposition === 'active')
}

export function resolveDefaultBuildOptionSetIndex(record: FleetTableRecord): number {
  if (record.buildOptionSets.length === 0) {
    return -1
  }
  if (record.displayDefaultOptionSetIndex != null) {
    return record.displayDefaultOptionSetIndex
  }
  let bestIndex = 0
  for (let index = 1; index < record.buildOptionSets.length; index += 1) {
    if (
      record.buildOptionSets[index].solutionRankWeight >
      record.buildOptionSets[bestIndex].solutionRankWeight
    ) {
      bestIndex = index
    }
  }
  return bestIndex
}

export function defaultBuildOptionSet(record: FleetTableRecord): FleetBuildOptionSet | null {
  const index = resolveDefaultBuildOptionSetIndex(record)
  return index >= 0 ? record.buildOptionSets[index] : null
}

export function alternateBuildOptionSets(record: FleetTableRecord): FleetBuildOptionSet[] {
  const defaultIndex = resolveDefaultBuildOptionSetIndex(record)
  return record.buildOptionSets.filter((_, index) => index !== defaultIndex)
}

function resolvedOptionSetComponentId(
  optionSet: FleetBuildOptionSet,
  field: 'hull' | 'engine'
): number | null {
  const componentId = field === 'hull' ? optionSet.hullId : optionSet.engineId
  if (componentId == null || componentId <= 0) {
    return null
  }
  return componentId
}

function optionSetFieldFallback(
  optionSet: FleetBuildOptionSet | null,
  field: FleetRecordFieldKey
): string | null {
  if (optionSet == null) {
    return null
  }
  switch (field) {
    case 'hull': {
      const hullId = resolvedOptionSetComponentId(optionSet, 'hull')
      if (hullId != null) {
        return String(hullId)
      }
      if (optionSet.label.length > 0) {
        return optionSet.label
      }
      return null
    }
    case 'engine': {
      const engineId = resolvedOptionSetComponentId(optionSet, 'engine')
      return engineId != null ? String(engineId) : null
    }
    case 'beams':
      return String(optionSet.beamCount)
    case 'launchers':
      return String(optionSet.launcherCount)
    default:
      return null
  }
}

export function formatFleetFieldConstraint(
  constraint: FleetFieldConstraint | undefined,
  field: FleetRecordFieldKey,
  optionSet: FleetBuildOptionSet | null = null
): string {
  if (constraint == null) {
    return optionSetFieldFallback(optionSet, field) ?? '?'
  }

  switch (constraint.kind) {
    case 'known':
      return String(constraint.value)
    case 'unknown':
      return optionSetFieldFallback(optionSet, field) ?? '?'
    case 'bounded':
      return `${BOUNDED_OPERATOR_LABEL[constraint.operator]} ${constraint.value}`
    case 'options':
      return constraint.values.map(String).join(' | ')
    case 'region': {
      const parts: string[] = []
      if (constraint.planetIds != null && constraint.planetIds.length > 0) {
        parts.push(`planet ${constraint.planetIds.join(', ')}`)
      }
      if (constraint.starbaseCoords != null && constraint.starbaseCoords.length > 0) {
        parts.push(
          constraint.starbaseCoords
            .map((coord) => `(${coord.x}, ${coord.y})`)
            .join(', ')
        )
      }
      if (constraint.overlayId != null && constraint.overlayId.length > 0) {
        parts.push(constraint.overlayId)
      }
      return parts.length > 0 ? parts.join('; ') : '?'
    }
    default:
      return '?'
  }
}

export function formatFleetRecordField(
  record: FleetTableRecord,
  field: FleetRecordFieldKey
): string {
  const optionSet = defaultBuildOptionSet(record)
  const constraint = record.fields?.[field]
  return formatFleetFieldConstraint(constraint, field, optionSet)
}

export function formatFleetLastSeen(lastSeen: FleetLastSeen | undefined): string {
  if (lastSeen == null) {
    return '—'
  }
  const position =
    lastSeen.planetId != null
      ? `planet ${lastSeen.planetId}`
      : `(${lastSeen.x}, ${lastSeen.y})`
  return `T${lastSeen.turn} ${position}`
}

export function formatBuildOptionSetSummary(optionSet: FleetBuildOptionSet): string {
  const parts = [
    optionSet.label,
    optionSet.hullId != null ? `hull ${optionSet.hullId}` : null,
    optionSet.engineId != null ? `engine ${optionSet.engineId}` : null,
    `beams ${optionSet.beamCount}`,
    `launchers ${optionSet.launcherCount}`,
  ].filter((part): part is string => part != null)
  return parts.join(' · ')
}

export function formatFleetCountDiscrepancyBanner(
  activeRowCount: number,
  scoreboardImpliedCount: number,
  hostTurn: number
): string {
  return `Fleet count discrepancy on turn ${hostTurn}: ${activeRowCount} active rows vs ${scoreboardImpliedCount} implied by scoreboard`
}
