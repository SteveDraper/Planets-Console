import type { StellarCartographySampleEntry } from '../../api/bff'

function formatStarClusterSampleLine(line: string): string {
  const separatorIndex = line.indexOf(' — ')
  if (separatorIndex === -1) {
    return `${line} star cluster`
  }
  const name = line.slice(0, separatorIndex)
  const details = line.slice(separatorIndex + 3)
  return `${name} star cluster — ${details}`
}

export function formatStellarCartographySampleLine(entry: StellarCartographySampleEntry): string {
  switch (entry.layer) {
    case 'nebulae': {
      const [name, visibilityLy] = entry.lines
      return `${name} nebula, visibility ${visibilityLy ?? '—'}`
    }
    case 'ion-storms':
      return `Ion storm: ${entry.lines.join(' — ')}`
    case 'star-clusters': {
      return entry.lines.map(formatStarClusterSampleLine).join(' — ')
    }
    case 'black-holes':
      return `Black hole: ${entry.lines.join(' ')}`
    case 'wormholes':
      return entry.lines.join(' ')
    default:
      return entry.lines.join(' ')
  }
}
