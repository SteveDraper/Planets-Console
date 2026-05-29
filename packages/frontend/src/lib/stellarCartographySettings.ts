import type { GameInfoResponse } from '../api/bff'
import {
  EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES,
  type StellarCartographySettingsGates,
} from '../analytics/stellar-cartography/layers'

function settingsCount(data: GameInfoResponse | null | undefined, key: string): number {
  for (const block of [data?.settings, data?.game]) {
    if (block == null || typeof block !== 'object' || Array.isArray(block)) {
      continue
    }
    const value = (block as Record<string, unknown>)[key]
    if (typeof value === 'number' && Number.isFinite(value)) {
      return value
    }
  }
  return 0
}

export function stellarCartographySettingsGatesFromGameInfo(
  data: GameInfoResponse | null | undefined
): StellarCartographySettingsGates {
  if (data == null) {
    return { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES }
  }
  return {
    debrisDiskBorders: settingsCount(data, 'ndebrisdiscs') > 0,
    starClusters: settingsCount(data, 'stars') > 0,
    nebulae: settingsCount(data, 'nebulas') > 0,
    ionStorms: settingsCount(data, 'maxions') > 0,
    wormholes: settingsCount(data, 'maxwormholes') > 0,
    blackHoles: settingsCount(data, 'blackholes') > 0,
  }
}
