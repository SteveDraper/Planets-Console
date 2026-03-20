import { useCallback, useMemo, useRef, useState } from 'react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { Header } from './components/Header'
import { AnalyticsBar } from './components/AnalyticsBar'
import { MainArea } from './components/MainArea'
import { fetchAnalytics } from './api/bff'

const queryClient = new QueryClient()

function ConsoleShell() {
  const [viewMode, setViewMode] = useState<'tabular' | 'map'>('tabular')
  /** React Flow zoom (same as mousewheel); 1 = 100% on slider. Updated by MapGraph. */
  const [mapZoom, setMapZoom] = useState(1)
  const setMapZoomFromSlider = useRef<(z: number) => void | undefined>(undefined)
  const [enabledIds, setEnabledIds] = useState<Set<string>>(new Set())
  const [selectedGameId, setSelectedGameId] = useState<string | null>(null)

  const { data: analyticsData, isPending, error } = useQuery({
    queryKey: ['bff', 'analytics'],
    queryFn: fetchAnalytics,
  })

  const analytics = analyticsData?.analytics ?? []
  const enabledAnalyticIds = useMemo(
    () => analytics.filter((a) => enabledIds.has(a.id)).map((a) => a.id),
    [analytics, enabledIds]
  )
  const handleMapZoomChange = useCallback((z: number) => {
    if (Number.isFinite(z) && z > 0) setMapZoom(Math.min(40, Math.max(0.2, z)))
  }, [])
  const handleSetZoomReady = useCallback((fn: (z: number) => void) => {
    setMapZoomFromSlider.current = fn
  }, [])
  const handleMapZoomSliderChange = useCallback((z: number) => {
    setMapZoomFromSlider.current?.(z)
  }, [])

  const toggleAnalytic = (id: string) => {
    setEnabledIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="flex h-screen flex-col bg-black">
      <Header
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        mapZoom={mapZoom}
        onMapZoomSliderChange={handleMapZoomSliderChange}
        selectedGameId={selectedGameId}
        onSelectGameId={setSelectedGameId}
      />
      <div className="flex min-h-0 flex-1">
        <AnalyticsBar
          analytics={analytics}
          enabledIds={enabledIds}
          onToggle={toggleAnalytic}
          viewMode={viewMode}
        />
        {isPending ? (
          <main className="flex flex-1 items-center justify-center bg-black p-8 text-gray-400">
            Loading analytics…
          </main>
        ) : error ? (
          <main className="flex flex-1 items-center justify-center bg-black p-8 text-red-400">
            Failed to load analytics
          </main>
        ) : (
          <MainArea
            viewMode={viewMode}
            enabledAnalyticIds={enabledAnalyticIds}
            analytics={analytics}
            onMapZoomChange={handleMapZoomChange}
            onSetZoomReady={handleSetZoomReady}
          />
        )}
      </div>
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ConsoleShell />
    </QueryClientProvider>
  )
}
