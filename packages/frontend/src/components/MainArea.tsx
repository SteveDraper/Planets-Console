import { memo, useState, type ReactNode } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '../lib/utils'
import type { AnalyticItem, AnalyticShellScope } from '../api/bff'
import { GenericTableTile } from '../analytics/GenericTableTile'
import { ShellLivedStreamTree } from '../analytics/ShellLivedStreamTree'
import { shellAnalyticRegistrationFor } from '../analytics/shellAnalyticRegistry'
import { isStellarCartographyMapEnabled } from '../analytics/mapShellCartography'
import {
  DEFAULT_PLANET_LABEL_OPTIONS,
  type PlanetLabelOptions,
} from './planetMapLabelModel'
import { ShellCenterPane, ShellErrorPane } from './shell/ShellPlaceholders'
import { MapShellContent, type MapShellContentProps } from './shell/MapShellContent'
import { deriveTurnEnsureLoadingView } from '../lib/mapDisplayRetention'
import { enabledTableAnalyticIds } from '../lib/enabledModeAnalyticIds'
import { useMapAnalyticQueries } from '../lib/useMapAnalyticQueries'
import { useRetainedMapDisplay } from '../lib/useRetainedMapDisplay'
import { useStellarCartographyMapContext } from '../lib/useStellarCartographyMapContext'
import type { PerspectiveRow } from '../lib/gameInfoShell'
import { useShellStore } from '../stores/shell'

const EMPTY_PERSPECTIVES: readonly PerspectiveRow[] = []

type ViewMode = 'tabular' | 'map'

function AnalyticTableSection({ title, children }: { title: string; children: ReactNode }) {
  const [expanded, setExpanded] = useState(true)

  return (
    <section className="rounded-lg border border-[#52575d] bg-[#40454a] shadow-sm">
      <button
        type="button"
        aria-expanded={expanded}
        aria-label={expanded ? `Collapse ${title}` : `Expand ${title}`}
        onClick={() => setExpanded((value) => !value)}
        className={cn(
          'flex w-full items-center gap-2 px-4 py-2 text-left text-sm font-medium text-slate-200 transition-colors hover:bg-black/10 focus-visible:outline focus-visible:ring-1 focus-visible:ring-slate-500',
          expanded && 'border-b border-[#52575d]'
        )}
      >
        <ChevronDown
          className={cn(
            'h-4 w-4 shrink-0 text-slate-400 transition-transform duration-150',
            !expanded && '-rotate-90'
          )}
          aria-hidden
        />
        <span>{title}</span>
      </button>
      {expanded ? children : null}
    </section>
  )
}

type MainAreaProps = {
  viewMode: ViewMode
  enabledAnalyticIds: string[]
  analytics: AnalyticItem[]
  /** When null, tabular/map analytic data is not requested (missing game, turn, or perspective). */
  analyticScope: AnalyticShellScope | null
  /** When true, turn data for `analyticScope` is present in storage (ensure query succeeded). */
  turnDataReady: boolean
  turnEnsurePending: boolean
  turnEnsureIsError: boolean
  /** TanStack `error` for the turn-ensure query (shown inline when `turnEnsureIsError`). */
  turnEnsureError: unknown
  /** Scope is set but login name is missing, so turn cannot be ensured. */
  turnBlockedNoLogin: boolean
  /** Turns beyond latest stored game turn for ion storm prediction. */
  futureTurnOffset: number
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
}

type MapMainAreaProps = {
  enabledAnalyticIds: string[]
  analytics: AnalyticItem[]
  analyticScope: AnalyticShellScope | null
  turnDataReady: boolean
  turnEnsurePending: boolean
  futureTurnOffset: number
  planetLabelOptions: PlanetLabelOptions
  onPlanetLabelOptionsChange: (value: PlanetLabelOptions) => void
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
}

type MapShellContentBaseProps = Omit<MapShellContentProps, 'cartography'>

/** Subscribes to live Stellar Cartography UI when that analytic is enabled on the map. */
function MapShellContentWithCartography(props: MapShellContentBaseProps) {
  const cartography = useStellarCartographyMapContext(props.analyticScope)
  return <MapShellContent {...props} cartography={cartography} />
}

/** Map queries and retention run only while this component is mounted (map view). */
const MapMainArea = memo(function MapMainArea({
  enabledAnalyticIds,
  analytics,
  analyticScope,
  turnDataReady,
  turnEnsurePending,
  futureTurnOffset,
  planetLabelOptions,
  onPlanetLabelOptionsChange,
  onMapZoomChange,
  onSetZoomReady,
}: MapMainAreaProps) {
  const analyticFetchEnabled = analyticScope != null && turnDataReady
  const roster =
    useShellStore((s) => s.gameInfoContext?.perspectives) ?? EMPTY_PERSPECTIVES
  const mapQueries = useMapAnalyticQueries({
    enabledAnalyticIds,
    analytics,
    analyticScope,
    analyticFetchEnabled,
  })

  const {
    enabledMapIds,
    mapIds,
    pending,
    hasError,
    hasAnyData,
    mapError,
    homeworldMapLayerSucceeded,
  } = mapQueries

  const { mapShellView } = useRetainedMapDisplay({
    combined: mapQueries.combined,
    gameId: analyticScope?.gameId ?? null,
    perspective: analyticScope?.perspective ?? null,
    mapIds,
    turnDataReady,
    turnEnsurePending,
    mapPending: pending,
    mapHasError: hasError,
    mapHasAnyData: hasAnyData,
    mapError,
  })

  if (analyticScope == null) {
    return (
      <ShellCenterPane message="Load game info and choose a turn and viewpoint to load the map." />
    )
  }

  if (mapIds.length === 0) {
    return (
      <ShellCenterPane message="No base map available. Enable at least one map-capable analytic to see the map." />
    )
  }

  const shellProps: MapShellContentBaseProps = {
    mapShellView,
    analyticScope,
    roster,
    homeworldMapLayerSucceeded,
    futureTurnOffset,
    planetLabelOptions,
    onPlanetLabelOptionsChange,
    onMapZoomChange,
    onSetZoomReady,
  }

  if (isStellarCartographyMapEnabled(enabledMapIds)) {
    return <MapShellContentWithCartography {...shellProps} />
  }

  return <MapShellContent {...shellProps} cartography={undefined} />
})

export function MainArea({
  viewMode,
  enabledAnalyticIds,
  analytics,
  analyticScope,
  turnDataReady,
  turnEnsurePending,
  turnEnsureIsError,
  turnEnsureError,
  turnBlockedNoLogin,
  futureTurnOffset,
  onMapZoomChange,
  onSetZoomReady,
}: MainAreaProps) {
  const analyticFetchEnabled = analyticScope != null && turnDataReady
  const [planetLabelOptions, setPlanetLabelOptions] = useState<PlanetLabelOptions>(
    DEFAULT_PLANET_LABEL_OPTIONS
  )
  const tableAnalyticIds =
    viewMode === 'tabular' ? enabledTableAnalyticIds(enabledAnalyticIds, analytics) : []
  const streamEnabled = analyticFetchEnabled && !turnBlockedNoLogin

  if (viewMode === 'tabular' && tableAnalyticIds.length === 0) {
    return <ShellCenterPane message="Enable at least one analytic in the left bar." />
  }

  if (analyticScope != null && turnBlockedNoLogin) {
    return (
      <ShellCenterPane message="Set login name in the header to load turn data for analytics." />
    )
  }

  if (analyticScope != null && !turnDataReady && turnEnsureIsError) {
    return (
      <ShellErrorPane
        title="Failed to load turn data"
        error={turnEnsureError}
        footer="See the error bar, or try another turn or viewpoint."
      />
    )
  }

  const turnEnsureLoading = deriveTurnEnsureLoadingView({
    hasAnalyticScope: analyticScope != null,
    turnDataReady,
    turnEnsurePending,
  })

  if (viewMode === 'tabular') {
    if (turnEnsureLoading.show) {
      return <ShellCenterPane message={turnEnsureLoading.loadingMessage} />
    }

    return (
      <ShellLivedStreamTree
        analyticScope={analyticScope}
        enabledAnalyticIds={enabledAnalyticIds}
        streamEnabled={streamEnabled}
      >
        <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto bg-black p-4">
          {tableAnalyticIds.map((id) => {
            const TableView =
              shellAnalyticRegistrationFor(id)?.TableView ?? GenericTableTile
            return (
              <AnalyticTableSection
                key={id}
                title={analytics.find((a) => a.id === id)?.name ?? id}
              >
                <TableView
                  analyticId={id}
                  analyticScope={analyticScope}
                  fetchEnabled={analyticFetchEnabled}
                />
              </AnalyticTableSection>
            )
          })}
        </main>
      </ShellLivedStreamTree>
    )
  }

  return (
    <ShellLivedStreamTree
      analyticScope={analyticScope}
      enabledAnalyticIds={enabledAnalyticIds}
      streamEnabled={streamEnabled}
    >
      <MapMainArea
        enabledAnalyticIds={enabledAnalyticIds}
        analytics={analytics}
        analyticScope={analyticScope}
        turnDataReady={turnDataReady}
        turnEnsurePending={turnEnsurePending}
        futureTurnOffset={futureTurnOffset}
        planetLabelOptions={planetLabelOptions}
        onPlanetLabelOptionsChange={setPlanetLabelOptions}
        onMapZoomChange={onMapZoomChange}
        onSetZoomReady={onSetZoomReady}
      />
    </ShellLivedStreamTree>
  )
}
