import {
  buildMineralRows,
  buildPlanetTitleLine,
  formatNativesLine,
  formatOwnershipLine,
  getPlanetDataAvailability,
  remainingPlanetEntries,
  type PlanetDataAvailability,
  type PlanetLabelOptions,
  type PlanetWire,
} from './planetMapLabelModel'

type PlanetMapLabelProps = {
  options: PlanetLabelOptions
  nodeId: string
  planet: PlanetWire | undefined
  ownerName: string | null | undefined
  planetX: number
  planetY: number
}

function formatTemp(planet: PlanetWire | undefined): string {
  if (planet == null) return '—'
  const t = planet.temp
  return typeof t === 'number' && Number.isFinite(t) ? String(t) : '—'
}

function formatClans(planet: PlanetWire | undefined): string {
  if (planet == null) return 'Colonist clans: —'
  const c = planet.clans
  return typeof c === 'number' && Number.isFinite(c) ? `Colonist clans: ${c}` : 'Colonist clans: —'
}

function LowDetailBlock({ planet, ownerName }: { planet: PlanetWire | undefined; ownerName: string | null | undefined }) {
  return (
    <div className="space-y-0.5 text-[10px] leading-snug text-gray-300">
      <div>Temperature: {formatTemp(planet)}</div>
      <div>{formatNativesLine(planet)}</div>
      <div>{formatOwnershipLine(planet, ownerName)}</div>
      <div>{formatClans(planet)}</div>
    </div>
  )
}

function MaskedPropertySection({
  availability,
  planet,
  ownerName,
}: {
  availability: PlanetDataAvailability
  planet: PlanetWire | undefined
  ownerName: string | null | undefined
}) {
  if (availability === 'NO_DATA') {
    return <div className="text-[10px] text-gray-400">Unknown</div>
  }
  if (availability === 'OWNERSHIP_ONLY') {
    return (
      <div className="space-y-0.5 text-[10px] leading-snug text-gray-300">
        <div>{formatOwnershipLine(planet, ownerName)}</div>
      </div>
    )
  }
  if (availability === 'BASIC_INFO') {
    return (
      <div className="space-y-0.5 text-[10px] leading-snug text-gray-300">
        <div>Temperature: {formatTemp(planet)}</div>
        <div>{formatNativesLine(planet)}</div>
        <div>{formatOwnershipLine(planet, ownerName)}</div>
        <div>{formatClans(planet)}</div>
      </div>
    )
  }
  return <LowDetailBlock planet={planet} ownerName={ownerName} />
}

function MineralTable({ planet }: { planet: PlanetWire | undefined }) {
  const rows = buildMineralRows(planet)
  const groundWidths = rows.map((r) => r.ground.length)
  const maxGround = Math.max(4, ...groundWidths)

  return (
    <table className="w-full border-collapse font-mono text-[10px] text-gray-300">
      <tbody>
        {rows.map((r) => (
          <tr key={r.label}>
            <td className="pr-2 text-left text-gray-400">{r.label}</td>
            <td className="pr-2 text-right tabular-nums">{r.surface}</td>
            <td className="pr-2 text-right tabular-nums" style={{ minWidth: `${maxGround}ch` }}>
              {r.ground}
            </td>
            <td className="text-right text-gray-400">({r.density})</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function DebugDetailBlock({ planet }: { planet: PlanetWire | undefined }) {
  const entries = remainingPlanetEntries(planet)
  if (entries.length === 0) return null
  return (
    <div className="space-y-0.5 text-[10px] leading-snug text-gray-300">
      {entries.map(([k, v]) => (
        <div key={k} className="flex gap-2">
          <span className="shrink-0 text-gray-500">{k}</span>
          <span className="min-w-0 break-all">{v}</span>
        </div>
      ))}
    </div>
  )
}

export function PlanetMapLabel({ options, nodeId, planet, ownerName, planetX, planetY }: PlanetMapLabelProps) {
  const title = buildPlanetTitleLine(options, planet, planetX, planetY, nodeId)
  const level = options.detailsLevel
  const availability = getPlanetDataAvailability(planet)

  const opaquePanelStyle = { backgroundColor: '#000000' } as const

  if (level === 'none') {
    return (
      <span
        className="isolate inline-block rounded border border-[#52575d] px-2 py-0.5 shadow-lg"
        style={opaquePanelStyle}
      >
        {title}
      </span>
    )
  }

  if (level === 'debug') {
    return (
      <div
        className="isolate max-w-sm overflow-hidden rounded border border-[#52575d] px-2 py-1.5 shadow-lg"
        style={opaquePanelStyle}
      >
        <div className="font-mono text-[10px] text-gray-200">{title}</div>
        <div className="my-1.5 border-t border-[#52575d]" />
        <div
          className="max-h-[min(280px,50vh)] space-y-2 overflow-y-auto overflow-x-hidden bg-[#000000] pr-0.5 [scrollbar-gutter:stable]"
          style={opaquePanelStyle}
        >
          <LowDetailBlock planet={planet} ownerName={ownerName} />
          <MineralTable planet={planet} />
          <DebugDetailBlock planet={planet} />
        </div>
      </div>
    )
  }

  const masked = <MaskedPropertySection availability={availability} planet={planet} ownerName={ownerName} />
  const mediumBody =
    availability === 'FULL_INFO' ? (
      <div className="space-y-2">
        {masked}
        <MineralTable planet={planet} />
      </div>
    ) : (
      masked
    )

  return (
    <div
      className="isolate max-w-sm overflow-hidden rounded border border-[#52575d] px-2 py-1.5 shadow-lg"
      style={opaquePanelStyle}
    >
      <div className="font-mono text-[10px] text-gray-200">{title}</div>
      <div className="my-1.5 border-t border-[#52575d]" />
      {level === 'low' ? masked : mediumBody}
    </div>
  )
}
