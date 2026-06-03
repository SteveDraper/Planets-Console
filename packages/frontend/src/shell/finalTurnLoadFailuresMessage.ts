import {
  viewpointNameForStoredPerspective,
  type PerspectiveRow,
} from '../lib/gameInfoShell'

function formatPerspectiveFailureLabel(
  ordinal: number,
  perspectives: PerspectiveRow[]
): string {
  const name = viewpointNameForStoredPerspective(ordinal, perspectives)
  if (name != null) {
    return `${name} (perspective ${ordinal})`
  }
  return `perspective ${ordinal}`
}

function joinLabels(labels: string[]): string {
  if (labels.length === 1) {
    return labels[0]
  }
  if (labels.length === 2) {
    return `${labels[0]} and ${labels[1]}`
  }
  return `${labels.slice(0, -1).join(', ')}, and ${labels[labels.length - 1]}`
}

/** User-visible shell message when load-all completes with final turn fetch gaps. */
export function formatFinalTurnLoadFailuresMessage(
  failures: number[],
  perspectives: PerspectiveRow[]
): string {
  const labels = failures.map((ordinal) =>
    formatPerspectiveFailureLabel(ordinal, perspectives)
  )
  const joined = joinLabels(labels)
  return (
    `Load-all finished but the final turn could not be fetched for ${joined}. ` +
    'Retry Load all turns or change turn to load the latest turn manually.'
  )
}
