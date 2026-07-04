import {
  FLEET_MATERIALIZATION_PENDING_SUMMARY,
  type FleetPlayerStreamSlice,
} from './fleetTablePlayerStreamState'

export function fleetTileProgressSummary(streamSlice: FleetPlayerStreamSlice | undefined): string {
  if (streamSlice == null) {
    return FLEET_MATERIALIZATION_PENDING_SUMMARY
  }
  if (streamSlice.error != null) {
    return streamSlice.error
  }
  if (streamSlice.summary.length > 0) {
    return streamSlice.summary
  }
  return FLEET_MATERIALIZATION_PENDING_SUMMARY
}

export function isFleetTileMaterializing(streamSlice: FleetPlayerStreamSlice | undefined): boolean {
  if (streamSlice == null) {
    return true
  }
  if (streamSlice.error != null || streamSlice.isComplete) {
    return false
  }
  return true
}

export function isFleetTileActivelyMaterializing(
  streamSlice: FleetPlayerStreamSlice | undefined
): boolean {
  if (!isFleetTileMaterializing(streamSlice)) {
    return false
  }
  return (streamSlice?.records?.length ?? 0) === 0
}
