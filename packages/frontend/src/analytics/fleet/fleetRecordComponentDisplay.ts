import { GENERIC_FREIGHTER_HULL_ID } from '../../concepts/hullImageUrl'
import type { FleetBuildOptionSet, FleetFieldConstraint, FleetTableRecord } from './fleetTableWireSchema'
import {
  type FleetComponentCatalog,
  fleetBeamName,
  fleetEngineName,
  fleetHullName,
  fleetTorpedoName,
  formatComponentQuantityLabel,
} from './fleetComponentCatalog'
import { defaultBuildOptionSet } from './fleetRecordDisplay'

const GENERIC_FREIGHTER_COMBO_ID = 'combo_freighter'

function knownComponentId(constraint: FleetFieldConstraint | undefined): number | null {
  if (constraint?.kind !== 'known') {
    return null
  }
  const value = constraint.value
  if (typeof value !== 'number' || value <= 0) {
    return null
  }
  return value
}

function isGenericFreighterOptionSet(optionSet: FleetBuildOptionSet | null): boolean {
  return optionSet?.comboId === GENERIC_FREIGHTER_COMBO_ID
}

function resolveHullId(
  record: FleetTableRecord,
  optionSet: FleetBuildOptionSet | null
): number | null {
  const fromField = knownComponentId(record.fields?.hull)
  if (fromField != null) {
    return fromField
  }
  if (optionSet?.hullId != null && optionSet.hullId > 0) {
    return optionSet.hullId
  }
  if (optionSet?.comboId === GENERIC_FREIGHTER_COMBO_ID) {
    return GENERIC_FREIGHTER_HULL_ID
  }
  return null
}

function resolveEngineId(
  record: FleetTableRecord,
  optionSet: FleetBuildOptionSet | null
): number | null {
  const fromField = knownComponentId(record.fields?.engine)
  if (fromField != null) {
    return fromField
  }
  if (optionSet?.engineId != null && optionSet.engineId > 0) {
    return optionSet.engineId
  }
  return null
}

export type FleetHullDisplay = {
  hullId: number | null
  label: string
}

export function formatFleetHullDisplay(
  record: FleetTableRecord,
  catalog: FleetComponentCatalog,
  optionSet: FleetBuildOptionSet | null = defaultBuildOptionSet(record)
): FleetHullDisplay {
  if (isGenericFreighterOptionSet(optionSet) && optionSet!.label.length > 0) {
    return {
      hullId: GENERIC_FREIGHTER_HULL_ID,
      label: optionSet!.label,
    }
  }
  const hullId = resolveHullId(record, optionSet)
  if (hullId != null) {
    const hullName = fleetHullName(catalog, hullId)
    if (hullName != null) {
      return { hullId, label: hullName }
    }
    return { hullId, label: String(hullId) }
  }
  if (optionSet?.label.length) {
    return { hullId, label: optionSet.label }
  }
  return { hullId, label: '?' }
}

export function formatFleetEngineDisplay(
  record: FleetTableRecord,
  catalog: FleetComponentCatalog,
  optionSet: FleetBuildOptionSet | null = defaultBuildOptionSet(record)
): string {
  const engineId = resolveEngineId(record, optionSet)
  if (engineId != null) {
    const engineName = fleetEngineName(catalog, engineId)
    if (engineName != null) {
      return engineName
    }
    return String(engineId)
  }
  return '?'
}

export function formatFleetBeamsDisplay(
  record: FleetTableRecord,
  catalog: FleetComponentCatalog,
  optionSet: FleetBuildOptionSet | null = defaultBuildOptionSet(record)
): string {
  if (optionSet != null) {
    if (optionSet.beamCount == null) {
      return '?'
    }
    return formatComponentQuantityLabel(
      optionSet.beamCount,
      optionSet.beamId != null ? fleetBeamName(catalog, optionSet.beamId) : null,
      optionSet.beamId ?? null
    )
  }
  const beamId = knownComponentId(record.fields?.beams)
  if (beamId != null) {
    return fleetBeamName(catalog, beamId) ?? String(beamId)
  }
  const beams = record.fields?.beams
  if (beams?.kind === 'known' && beams.value === 0) {
    return '0'
  }
  return '?'
}

export function formatFleetLaunchersDisplay(
  record: FleetTableRecord,
  catalog: FleetComponentCatalog,
  optionSet: FleetBuildOptionSet | null = defaultBuildOptionSet(record)
): string {
  if (optionSet != null) {
    if (optionSet.launcherCount == null) {
      return '?'
    }
    return formatComponentQuantityLabel(
      optionSet.launcherCount,
      optionSet.torpId != null ? fleetTorpedoName(catalog, optionSet.torpId) : null,
      optionSet.torpId ?? null
    )
  }
  const torpId = knownComponentId(record.fields?.launchers)
  if (torpId != null) {
    return fleetTorpedoName(catalog, torpId) ?? String(torpId)
  }
  const launchers = record.fields?.launchers
  if (launchers?.kind === 'known' && launchers.value === 0) {
    return '0'
  }
  return '?'
}

export function formatBuildOptionSetComponentSummary(
  optionSet: FleetBuildOptionSet,
  catalog: FleetComponentCatalog
): string {
  const parts: string[] = []
  if (optionSet.hullId != null && optionSet.hullId > 0) {
    parts.push(fleetHullName(catalog, optionSet.hullId) ?? `hull ${optionSet.hullId}`)
  } else if (optionSet.label.length > 0) {
    parts.push(optionSet.label)
  }
  if (optionSet.engineId != null && optionSet.engineId > 0) {
    parts.push(fleetEngineName(catalog, optionSet.engineId) ?? `engine ${optionSet.engineId}`)
  }
  parts.push(
    optionSet.beamCount == null
      ? '?'
      : formatComponentQuantityLabel(
          optionSet.beamCount,
          optionSet.beamId != null ? fleetBeamName(catalog, optionSet.beamId) : null,
          optionSet.beamId ?? null
        )
  )
  parts.push(
    optionSet.launcherCount == null
      ? '?'
      : formatComponentQuantityLabel(
          optionSet.launcherCount,
          optionSet.torpId != null ? fleetTorpedoName(catalog, optionSet.torpId) : null,
          optionSet.torpId ?? null
        )
  )
  return parts.join(' · ')
}
