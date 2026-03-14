import { cn } from '../lib/utils'

type ViewMode = 'tabular' | 'map'

type HeaderProps = {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  scale: number
  onScaleChange: (n: number) => void
}

export function Header({ viewMode, onViewModeChange, scale, onScaleChange }: HeaderProps) {
  const isMapMode = viewMode === 'map'

  return (
    <header className="flex shrink-0 items-center gap-4 border-b border-gray-200 bg-gray-50 px-4 py-2 dark:border-gray-700 dark:bg-gray-800">
      <span className="text-sm text-gray-500 dark:text-gray-400" title="Login identity">
        Login: <span className="text-gray-700 dark:text-gray-200">—</span>
      </span>
      <span className="text-sm text-gray-500 dark:text-gray-400" title="Game">
        Game: <span className="text-gray-700 dark:text-gray-200">—</span>
      </span>
      <span className="text-sm text-gray-500 dark:text-gray-400" title="Turn">
        Turn: <span className="text-gray-700 dark:text-gray-200">—</span>
      </span>
      <span className="text-sm text-gray-500 dark:text-gray-400" title="Viewpoint">
        Viewpoint: <span className="text-gray-700 dark:text-gray-200">—</span>
      </span>
      <div className="ml-auto flex items-center gap-2">
        <div className="flex rounded-md border border-gray-300 dark:border-gray-600">
          <button
            type="button"
            onClick={() => onViewModeChange('tabular')}
            className={cn(
              'px-3 py-1.5 text-sm font-medium',
              viewMode === 'tabular'
                ? 'bg-gray-200 text-gray-900 dark:bg-gray-600 dark:text-white'
                : 'bg-transparent text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
            )}
          >
            Tabular
          </button>
          <button
            type="button"
            onClick={() => onViewModeChange('map')}
            className={cn(
              'px-3 py-1.5 text-sm font-medium',
              viewMode === 'map'
                ? 'bg-gray-200 text-gray-900 dark:bg-gray-600 dark:text-white'
                : 'bg-transparent text-gray-600 hover:bg-gray-100 dark:text-gray-300 dark:hover:bg-gray-700'
            )}
          >
            Map
          </button>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500 dark:text-gray-400">Scale</span>
          <input
            type="range"
            min={50}
            max={150}
            value={scale}
            onChange={(e) => onScaleChange(Number(e.target.value))}
            disabled={!isMapMode}
            className={cn(
              'h-2 w-24 accent-gray-600 dark:accent-gray-400',
              !isMapMode && 'cursor-not-allowed opacity-50'
            )}
            title={isMapMode ? 'Map scale' : 'Enable map mode to use scale'}
          />
          <span className="w-8 text-xs text-gray-500 dark:text-gray-400">{scale}%</span>
        </div>
      </div>
    </header>
  )
}
