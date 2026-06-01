import type { AnalyticShellScope } from '../../api/bff'

/** Hover-panel context passed from the map shell; layer config is read inside MapGraph. */
export type StellarCartographyMapUi = {
  cartographyEnabled: boolean
  analyticScope: AnalyticShellScope | null
}
