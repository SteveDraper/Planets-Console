import { STELLAR_CARTOGRAPHY_ANALYTIC_ID } from './mapAnalyticIds'

/** True when Stellar Cartography is enabled on the map shell (live UI context required). */
export function isStellarCartographyMapEnabled(enabledMapIds: readonly string[]): boolean {
  return enabledMapIds.includes(STELLAR_CARTOGRAPHY_ANALYTIC_ID)
}
