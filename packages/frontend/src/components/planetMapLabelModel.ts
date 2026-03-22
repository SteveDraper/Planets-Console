export type PlanetDetailsLevel = 'none' | 'low' | 'medium' | 'debug'

export type PlanetLabelOptions = {
  includePlanetId: boolean
  includePlanetName: boolean
  includeCoordinates: boolean
  detailsLevel: PlanetDetailsLevel
}

export const DEFAULT_PLANET_LABEL_OPTIONS: PlanetLabelOptions = {
  includePlanetId: true,
  includePlanetName: false,
  includeCoordinates: false,
  detailsLevel: 'none',
}

export function planetLabelOptionsShowAnyLabel(options: PlanetLabelOptions): boolean {
  return options.includePlanetId || options.includePlanetName || options.includeCoordinates
}

export type PlanetWire = Record<string, unknown>

export const PlanetDataAvailability = {
  NO_DATA: 'NO_DATA',
  OWNERSHIP_ONLY: 'OWNERSHIP_ONLY',
  BASIC_INFO: 'BASIC_INFO',
  FULL_INFO: 'FULL_INFO',
} as const

export type PlanetDataAvailability =
  (typeof PlanetDataAvailability)[keyof typeof PlanetDataAvailability]

/**
 * How much structured planet data we trust for map labels (from host sentinels on temp / neutronium).
 *
 * - Unowned and temp &lt; 0: no scan data.
 * - Owned and temp &lt; 0: ownership is known; other fields are not.
 * - temp &gt;= 0 and surface neutronium &lt; 0: basic scan (no mineral breakdown).
 * - surface neutronium &gt;= 0: full scan including minerals.
 */
export function getPlanetDataAvailability(planet: PlanetWire | undefined): PlanetDataAvailability {
  if (planet == null) return PlanetDataAvailability.NO_DATA

  const oid = typeof planet.ownerid === 'number' ? planet.ownerid : null
  const unowned = oid === null || oid === 0
  const tempRaw = planet.temp
  const tempFinite = typeof tempRaw === 'number' && Number.isFinite(tempRaw)

  if (tempFinite && tempRaw < 0) {
    return unowned ? PlanetDataAvailability.NO_DATA : PlanetDataAvailability.OWNERSHIP_ONLY
  }

  const nRaw = planet.neutronium
  const nFinite = typeof nRaw === 'number' && Number.isFinite(nRaw)

  if (nFinite && nRaw >= 0) {
    return PlanetDataAvailability.FULL_INFO
  }

  if (tempFinite && tempRaw >= 0 && nFinite && nRaw < 0) {
    return PlanetDataAvailability.BASIC_INFO
  }

  return PlanetDataAvailability.NO_DATA
}

const MINERAL_KEYS = [
  { surface: 'neutronium', ground: 'groundneutronium', density: 'densityneutronium', label: 'Neutronium' },
  { surface: 'duranium', ground: 'groundduranium', density: 'densityduranium', label: 'Duranium' },
  { surface: 'tritanium', ground: 'groundtritanium', density: 'densitytritanium', label: 'Tritanium' },
  { surface: 'molybdenum', ground: 'groundmolybdenum', density: 'densitymolybdenum', label: 'Molybdenum' },
] as const

const LOW_MEDIUM_PLANET_KEYS = new Set<string>([
  'temp',
  'nativeracename',
  'nativeclans',
  'ownerid',
  'clans',
  ...MINERAL_KEYS.flatMap((m) => [m.surface, m.ground, m.density]),
])

function formatScalar(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number' && !Number.isFinite(value)) return '—'
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'number') return String(value)
  return String(value)
}

/** Ground mineral density is a percentage in host data. */
function formatMineralDensity(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    return Number.isFinite(value) ? `${value}%` : '—'
  }
  return formatScalar(value)
}

function planetNumericIdFromNodeId(rawNodeId: string): number | undefined {
  const last = rawNodeId.includes(':') ? rawNodeId.slice(rawNodeId.lastIndexOf(':') + 1) : rawNodeId
  const m = /^p(\d+)$/.exec(last)
  if (!m) return undefined
  const n = parseInt(m[1], 10)
  return Number.isFinite(n) ? n : undefined
}

/** Wire payloads may use number or string ids depending on JSON shape. */
function planetWireNumericId(planet: PlanetWire | undefined): number | undefined {
  if (planet == null) return undefined
  const raw = planet.id
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw
  if (typeof raw === 'string' && /^\d+$/.test(raw)) return parseInt(raw, 10)
  return undefined
}

function planetWireDisplayName(planet: PlanetWire | undefined): string {
  if (planet == null) return ''
  const raw = planet.name
  if (typeof raw === 'string') {
    const t = raw.trim()
    return t
  }
  return ''
}

export function buildPlanetTitleLine(
  options: PlanetLabelOptions,
  planet: PlanetWire | undefined,
  planetX: number,
  planetY: number,
  rawNodeId?: string
): string {
  const parts: string[] = []
  let pid = planetWireNumericId(planet)
  if (pid == null && rawNodeId != null) {
    pid = planetNumericIdFromNodeId(rawNodeId)
  }
  if (options.includePlanetId && pid != null) {
    parts.push(`p${pid}`)
  }
  if (options.includePlanetName) {
    const name = planetWireDisplayName(planet)
    if (name) parts.push(name)
  }
  if (options.includeCoordinates) {
    const x = Math.floor(Number.isFinite(planetX) ? planetX : 0)
    const y = Math.floor(Number.isFinite(planetY) ? planetY : 0)
    parts.push(`(${x}, ${y})`)
  }
  return parts.join(' ')
}

export function formatOwnershipLine(planet: PlanetWire | undefined, ownerName: string | null | undefined): string {
  if (planet == null) return 'Ownership: —'
  const oid = typeof planet.ownerid === 'number' ? planet.ownerid : null
  if (oid === 0 || oid === null) return 'Ownership: Unowned'
  if (ownerName != null && ownerName.trim() !== '') {
    return `Ownership: ${ownerName}`
  }
  return `Ownership: player ${oid}`
}

/** `NativeType.NONE` is 0 on the wire; no natives -- omit race and clan counts. */
export function formatNativesLine(planet: PlanetWire | undefined): string {
  if (planet == null) return 'Natives: —'
  const rawType = planet.nativetype
  if (typeof rawType === 'number' && Number.isFinite(rawType) && rawType === 0) {
    return 'Natives: None'
  }
  const rawRace = typeof planet.nativeracename === 'string' ? planet.nativeracename.trim() : ''
  const race =
    rawRace === ''
      ? '—'
      : rawRace.toLowerCase() === 'none'
        ? 'None'
        : rawRace
  const pop = planet.nativeclans
  const popStr =
    typeof pop === 'number' && Number.isFinite(pop)
      ? pop < 0
        ? 'None'
        : String(pop)
      : '—'
  if (race === 'None' && popStr === 'None') return 'Natives: None'
  return `Natives: ${race} / ${popStr}`
}

export type MineralRow = { label: string; surface: string; ground: string; density: string }

export function buildMineralRows(planet: PlanetWire | undefined): MineralRow[] {
  if (planet == null) return []
  return MINERAL_KEYS.map(({ surface, ground, density, label }) => ({
    label,
    surface: formatScalar(planet[surface]),
    ground: formatScalar(planet[ground]),
    density: formatMineralDensity(planet[density]),
  }))
}

export function remainingPlanetEntries(planet: PlanetWire | undefined): [string, string][] {
  if (planet == null) return []
  const keys = Object.keys(planet).filter((k) => !LOW_MEDIUM_PLANET_KEYS.has(k))
  keys.sort((a, b) => a.localeCompare(b))
  return keys.map((k) => [k, formatScalar(planet[k])])
}
