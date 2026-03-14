import { cn, mapSliderToZoom, mapZoomToSlider } from '../lib/utils'

type ViewMode = 'tabular' | 'map'

type HeaderProps = {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  /** Current map zoom (React Flow); drives log-scale slider. */
  mapZoom: number
  onMapZoomSliderChange: (zoom: number) => void
}

export function Header({
  viewMode,
  onViewModeChange,
  mapZoom,
  onMapZoomSliderChange,
}: HeaderProps) {
  const isMapMode = viewMode === 'map'

  return (
    <header className="flex shrink-0 items-center gap-3 border-b border-[#52575d] bg-[#40454a] px-3 py-1.5 text-slate-200">
      <span className="text-xs text-slate-400" title="Login identity">
        Login: <span className="text-slate-200">—</span>
      </span>
      <span className="text-xs text-slate-400" title="Game">
        Game: <span className="text-slate-200">—</span>
      </span>
      <span className="text-xs text-slate-400" title="Turn">
        Turn: <span className="text-slate-200">—</span>
      </span>
      <span className="text-xs text-slate-400" title="Viewpoint">
        Viewpoint: <span className="text-slate-200">—</span>
      </span>
      <div className="ml-auto flex items-center gap-2">
        <div className="flex rounded border border-[#52575d]">
          <button
            type="button"
            onClick={() => onViewModeChange('tabular')}
            className={cn(
              'px-2.5 py-1 text-xs font-medium text-slate-200',
              viewMode === 'tabular'
                ? 'bg-[#52575d] text-slate-100'
                : 'bg-transparent text-slate-400 hover:bg-white/10 hover:text-slate-300'
            )}
          >
            Tabular
          </button>
          <button
            type="button"
            onClick={() => onViewModeChange('map')}
            className={cn(
              'px-2.5 py-1 text-xs font-medium text-slate-200',
              viewMode === 'map'
                ? 'bg-[#52575d] text-slate-100'
                : 'bg-transparent text-slate-400 hover:bg-white/10 hover:text-slate-300'
            )}
          >
            Map
          </button>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-slate-400">Scale</span>
          <input
            type="range"
            min={0}
            max={1000}
            step={1}
            value={mapZoomToSlider(mapZoom)}
            onChange={(e) => onMapZoomSliderChange(mapSliderToZoom(Number(e.target.value)))}
            disabled={!isMapMode}
            className={cn(
              'h-1.5 w-32 accent-slate-400',
              !isMapMode && 'cursor-not-allowed opacity-50'
            )}
            title={
              isMapMode
                ? 'Map zoom — log scale: equal movement multiplies zoom by the same factor (same as scroll wheel)'
                : 'Enable map mode to use scale'
            }
          />
          <span className="w-10 text-right text-xs text-slate-400">
            {Number.isFinite(mapZoom) ? Math.round(mapZoom * 100) : 100}%
          </span>
        </div>
      </div>
    </header>
  )
}
