/**
 * Friendly copy for partial map-analytic failures (base map still visible).
 */

import { errorDetailFromUnknown } from './queryRetry'

export type MapLayerFailure = {
  analyticId: string
  /** Catalog display name when available. */
  analyticName?: string
  error: unknown
}

function labelForFailure(failure: MapLayerFailure): string {
  const name = failure.analyticName?.trim()
  if (name) return name
  return failure.analyticId
}

function formatOneFailure(failure: MapLayerFailure): string {
  const label = labelForFailure(failure)
  const detail = errorDetailFromUnknown(failure.error).trim()
  if (!detail) {
    return `${label} failed`
  }
  // Prefer "Name: detail" unless the detail already names the analytic.
  if (detail.toLowerCase().startsWith(label.toLowerCase())) {
    return detail
  }
  return `${label}: ${detail}`
}

/** One-line banner text: which layer(s) failed and why. */
export function formatMapLayerErrorBanner(failures: readonly MapLayerFailure[]): string {
  if (failures.length === 0) {
    return 'Some map analytics failed'
  }
  return failures.map(formatOneFailure).join(' · ')
}
