import { useState, useMemo } from 'react'
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { Header } from './components/Header'
import { AnalyticsBar } from './components/AnalyticsBar'
import { MainArea } from './components/MainArea'
import { fetchAnalytics } from './api/bff'

const queryClient = new QueryClient()

function ConsoleShell() {
  const [viewMode, setViewMode] = useState<'tabular' | 'map'>('tabular')
  const [scale, setScale] = useState(100)
  const [enabledIds, setEnabledIds] = useState<Set<string>>(new Set())

  const { data: analyticsData, isPending, error } = useQuery({
    queryKey: ['bff', 'analytics'],
    queryFn: fetchAnalytics,
  })

  const analytics = analyticsData?.analytics ?? []
  const enabledAnalyticIds = useMemo(
    () => analytics.filter((a) => enabledIds.has(a.id)).map((a) => a.id),
    [analytics, enabledIds]
  )

  const toggleAnalytic = (id: string) => {
    setEnabledIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <div className="flex h-screen flex-col">
      <Header
        viewMode={viewMode}
        onViewModeChange={setViewMode}
        scale={scale}
        onScaleChange={setScale}
      />
      <div className="flex min-h-0 flex-1">
        <AnalyticsBar
          analytics={analytics}
          enabledIds={enabledIds}
          onToggle={toggleAnalytic}
          viewMode={viewMode}
        />
        {isPending ? (
          <main className="flex flex-1 items-center justify-center p-8 text-gray-500">
            Loading analytics…
          </main>
        ) : error ? (
          <main className="flex flex-1 items-center justify-center p-8 text-red-600">
            Failed to load analytics
          </main>
        ) : (
          <MainArea
            viewMode={viewMode}
            enabledAnalyticIds={enabledAnalyticIds}
            analytics={analytics}
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
