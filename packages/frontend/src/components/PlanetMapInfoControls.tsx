import type { PlanetDetailsLevel, PlanetLabelOptions } from './planetMapLabelModel'

type PlanetMapInfoControlsProps = {
  value: PlanetLabelOptions
  onChange: (next: PlanetLabelOptions) => void
}

const DETAIL_OPTIONS: { value: PlanetDetailsLevel; label: string; description: string }[] = [
  { value: 'none', label: 'None', description: 'Show only title information' },
  { value: 'low', label: 'Low', description: 'Show basic details' },
  { value: 'medium', label: 'Medium', description: 'Show full resource details' },
  { value: 'debug', label: 'Debug', description: 'Show all properties' },
]

export function PlanetMapInfoControls({ value, onChange }: PlanetMapInfoControlsProps) {
  const setField = <K extends keyof PlanetLabelOptions>(key: K, v: PlanetLabelOptions[K]) => {
    onChange({ ...value, [key]: v })
  }

  const selectedDetailDescription =
    DETAIL_OPTIONS.find((o) => o.value === value.detailsLevel)?.description ?? ''

  return (
    <section className="space-y-2 text-gray-300">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-300">Planet info</h3>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            className="rounded border-[#52575d] bg-[#2d3136]"
            checked={value.includePlanetId}
            onChange={(e) => setField('includePlanetId', e.target.checked)}
          />
          <span className="whitespace-nowrap">Planet id</span>
        </label>
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            className="rounded border-[#52575d] bg-[#2d3136]"
            checked={value.includePlanetName}
            onChange={(e) => setField('includePlanetName', e.target.checked)}
          />
          <span className="whitespace-nowrap">Planet name</span>
        </label>
        <label className="flex cursor-pointer items-center gap-2">
          <input
            type="checkbox"
            className="rounded border-[#52575d] bg-[#2d3136]"
            checked={value.includeCoordinates}
            onChange={(e) => setField('includeCoordinates', e.target.checked)}
          />
          <span className="whitespace-nowrap">Coordinates</span>
        </label>
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className="shrink-0 text-xs text-gray-400">Detail level</span>
        <select
          className="w-auto max-w-xs min-w-[7.5rem] rounded border border-[#52575d] bg-[#2d3136] px-2 py-1 text-sm text-slate-200"
          value={value.detailsLevel}
          title={selectedDetailDescription}
          onChange={(e) => setField('detailsLevel', e.target.value as PlanetDetailsLevel)}
        >
          {DETAIL_OPTIONS.map((o) => (
            <option key={o.value} value={o.value} title={o.description}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
    </section>
  )
}
