import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { AnalyticShellScope, CombinedMapData } from '../api/bff'
import {
  buildCartographyMapFrame,
  cartographyDisplayEdges,
  type CartographyMapFrame,
} from '../analytics/stellar-cartography/cartographyDisplayModel'
import { cartographyFramePolicy } from '../analytics/stellar-cartography/cartographyVisibilityPolicy'
import type { StellarCartographyMapContext } from '../analytics/stellar-cartography/mapUiConfig'
import {
  MAP_ZOOM_MAX,
  MAP_ZOOM_MIN,
} from '../lib/mapZoom'
import { buildPlanetSpatialGrid } from '../lib/planetSpatialGrid'
import {
  DEFAULT_PLANET_LABEL_OPTIONS,
  type PlanetLabelOptions,
} from './planetMapLabelModel'
import { nodeTypes, toFlowNodes } from './map-graph/nodes'
import { edgeTypes, toEdges } from './map-graph/edges'
import { StellarCartographyOverlayPane } from './map-graph/StellarCartographyOverlayPane'
import { MapRegionOverlayPane } from './map-graph/MapRegionOverlayPane'
import { MapAttentionOrchestrator } from './map-graph/MapAttentionOrchestrator'
import { HomeworldMarkersOverlay } from './map-graph/HomeworldMarkersOverlay'
import { FleetLocationRingsOverlay } from './map-graph/FleetLocationRingsOverlay'
import { FleetLocationRingStacksProvider } from '../analytics/fleet/FleetLocationRingStacksContext'
import { useFleetLocationRingStacks } from '../analytics/fleet/useFleetLocationRingStacks'
import { HomeworldMapContextMenu } from '../analytics/homeworld-locator/HomeworldMapContextMenu'
import { HOMEWORLD_LOCATOR_ANALYTIC_ID } from '../analytics/homeworld-locator/constants'
import { FLEET_ANALYTIC_ID } from '../analytics/mapAnalyticIds'
import { buildHomeworldRegionOverlaysForPaint } from '../analytics/homeworld-locator/homeworldRegionPaint'
import {
  useEffectiveHomeworldSectorIndexes,
  useHomeworldRegionSelectionMaterialize,
} from '../analytics/homeworld-locator/useHomeworldRegionSelection'
import { applyVisibilityRegionPreferences } from '../analytics/visibility/visibilityRegionPreferences'
import { homeworldOverlaysReadyForMaterialize } from '../lib/homeworldRegionSelection'
import { isHomeworldSectorOverlay } from '../lib/homeworldSectorIndex'
import { useEnabledAnalyticsStore } from '../stores/enabledAnalytics'
import { useHomeworldLocatorSelectionStore } from '../stores/homeworldLocatorSelection'
import { useHomeworldRegionSelectionStore } from '../stores/homeworldRegionSelectionStore'
import { useVisibilityPreferencesStore } from '../stores/visibilityPreferences'
import type { PerspectiveRow } from '../lib/gameInfoShell'
import { useWormholeLineRevealStore } from '../stores/wormholeLineReveal'
import {
  buildLabelSourceByNodeId,
  FixedSizeDotsOverlay,
} from './map-graph/FixedSizeDotsOverlay'
import { CoordinateGridOverlay, FlowCoordinateReadout } from './map-graph/coordinateGrid'
import { NormalWarpWellOutlinesOverlay } from './map-graph/NormalWarpWellOutlinesOverlay'
import {
  InitialViewportFit,
  MapZoomKeyboardShortcuts,
  SliderZoomControl,
  ViewportZoomSync,
} from './map-graph/viewportControls'
import { MapInteractionSurface } from '../map-interaction/MapInteractionSurface'
import { PlanetMapInteraction } from '../map-interaction/contributors/PlanetMapInteraction'
import { FleetMapInteractionContributor } from '../map-interaction/contributors/FleetMapInteractionContributor'
import { RegionMapInteractionContributor } from '../map-interaction/contributors/RegionMapInteractionContributor'
import { CartographyMapInteractionContributor } from '../map-interaction/contributors/CartographyMapInteractionContributor'
import { WormholeMapInteractionContributor } from '../map-interaction/contributors/WormholeMapInteractionContributor'

type MapGraphProps = {
  data: CombinedMapData
  className?: string
  /**
   * True while any enabled map-layer query is still pending (shell deferred-pending).
   * Part of homeworld region materialize readiness (loading race).
   */
  mapLayersPending?: boolean
  /**
   * True when the homeworld-locator map query settled successfully.
   * Required so failure-empty overlays do not consume init-only ``all``.
   */
  homeworldMapLayerSucceeded?: boolean
  /**
   * True when ``data`` is the live query frame; false when showing a retained
   * prior-turn frame. Required so materialize does not consume overlays from
   * a stale retained map while live queries catch up.
   */
  displayMapFrameIsLive?: boolean
  /** Shell-owned scope; required for homeworld map context menu asserts. */
  analyticScope: AnalyticShellScope
  /** Shell-owned roster for homeworld ownership menu labels. */
  roster: readonly PerspectiveRow[]
  /** Turns beyond latest stored game turn for ion storm overlay extrapolation. */
  futureTurnOffset?: number
  onMapZoomChange: (zoom: number) => void
  /** Called once so the header slider can drive zoom (same as scroll wheel). */
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  planetLabelOptions?: PlanetLabelOptions
  /** Set when Stellar Cartography is enabled; drives overlays, wormholes, and hover sampling. */
  cartography?: StellarCartographyMapContext
}

/** Max time to wait for initial viewport fit before showing the map anyway (avoids staying invisible if fit never runs). */
const INITIAL_FIT_REVEAL_MS = 250

export function MapGraph({
  data,
  className,
  mapLayersPending = false,
  homeworldMapLayerSucceeded = false,
  displayMapFrameIsLive = true,
  analyticScope,
  roster,
  futureTurnOffset = 0,
  onMapZoomChange,
  onSetZoomReady,
  planetLabelOptions = DEFAULT_PLANET_LABEL_OPTIONS,
  cartography,
}: MapGraphProps) {
  const [initialFitDone, setInitialFitDone] = useState(false)
  const onInitialFitDone = useCallback(() => setInitialFitDone(true), [])

  useEffect(() => {
    const t = setTimeout(() => setInitialFitDone(true), INITIAL_FIT_REVEAL_MS)
    return () => clearTimeout(t)
  }, [])

  const policy = useMemo(() => cartographyFramePolicy(cartography), [cartography])
  const frame = useMemo(
    () => buildCartographyMapFrame(data, policy, futureTurnOffset),
    [data, policy, futureTurnOffset]
  )
  const nodes = useMemo(() => toFlowNodes(frame.nodes), [frame.nodes])
  const planetMapNodes = useMemo(
    () => frame.nodes.filter((n) => n.planet != null),
    [frame.nodes]
  )
  const planetGrid = useMemo(() => buildPlanetSpatialGrid(planetMapNodes), [planetMapNodes])
  const waypointGrid = useMemo(() => {
    const wps = data.routeWaypoints
    if (wps.length === 0) return null
    return buildPlanetSpatialGrid(wps.map((w) => ({ id: w.id, x: w.gx, y: w.gy })))
  }, [data.routeWaypoints])
  const labelSourceByNodeId = useMemo(
    () => buildLabelSourceByNodeId(planetMapNodes),
    [planetMapNodes]
  )

  return (
    <div
      className={`map-graph-cursor-default relative min-h-0 overflow-hidden bg-black ${className ?? 'h-[320px] w-full min-w-0'}`}
    >
      <div
        className="h-full w-full transition-opacity duration-150"
        style={{ opacity: initialFitDone ? 1 : 0 }}
      >
        <MapGraphFlow
          data={data}
          frame={frame}
          nodes={nodes}
          planetMapNodes={planetMapNodes}
          planetGrid={planetGrid}
          waypointGrid={waypointGrid}
          labelSourceByNodeId={labelSourceByNodeId}
          planetLabelOptions={planetLabelOptions}
          analyticScope={analyticScope}
          roster={roster}
          cartography={cartography}
          mapLayersPending={mapLayersPending}
          homeworldMapLayerSucceeded={homeworldMapLayerSucceeded}
          displayMapFrameIsLive={displayMapFrameIsLive}
          onMapZoomChange={onMapZoomChange}
          onSetZoomReady={onSetZoomReady}
          onInitialFitDone={onInitialFitDone}
        />
      </div>
    </div>
  )
}

type MapGraphFlowProps = {
  data: CombinedMapData
  frame: CartographyMapFrame
  nodes: ReturnType<typeof toFlowNodes>
  planetMapNodes: CombinedMapData['nodes']
  planetGrid: ReturnType<typeof buildPlanetSpatialGrid>
  waypointGrid: ReturnType<typeof buildPlanetSpatialGrid> | null
  labelSourceByNodeId: ReturnType<typeof buildLabelSourceByNodeId>
  planetLabelOptions: PlanetLabelOptions
  analyticScope: AnalyticShellScope
  roster: readonly PerspectiveRow[]
  cartography?: StellarCartographyMapContext
  mapLayersPending: boolean
  homeworldMapLayerSucceeded: boolean
  displayMapFrameIsLive: boolean
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  onInitialFitDone: () => void
}

function MapGraphFlow({
  data,
  frame,
  nodes,
  planetMapNodes,
  planetGrid,
  waypointGrid,
  labelSourceByNodeId,
  planetLabelOptions,
  analyticScope,
  roster,
  cartography,
  mapLayersPending,
  homeworldMapLayerSucceeded,
  displayMapFrameIsLive,
  onMapZoomChange,
  onSetZoomReady,
  onInitialFitDone,
}: MapGraphFlowProps) {
  const wormholeLineRevealKey = useWormholeLineRevealStore(
    (s) => s.wormholeLineRevealKey
  )

  const policy = useMemo(() => cartographyFramePolicy(cartography), [cartography])
  const displayMapEdges = useMemo(
    () => cartographyDisplayEdges(frame, policy, wormholeLineRevealKey),
    [frame, policy, wormholeLineRevealKey]
  )
  const edges = useMemo(() => toEdges(displayMapEdges), [displayMapEdges])
  const visibilityKinds = useVisibilityPreferencesStore((s) => s.kinds)
  const selection = useHomeworldLocatorSelectionStore((s) => s.selection)
  const enabledAnalyticIds = useEnabledAnalyticsStore((s) => s.enabledIds)
  const homeworldEnabled = enabledAnalyticIds.includes(HOMEWORLD_LOCATOR_ANALYTIC_ID)
  const fleetEnabled = enabledAnalyticIds.includes(FLEET_ANALYTIC_ID)
  const fleetStacks = useFleetLocationRingStacks(analyticScope, fleetEnabled)
  const showEnvelopeOverlays = useHomeworldRegionSelectionStore(
    (s) => s.showEnvelopeOverlays
  )

  // Homeworld sectors already merged into combined map data by the map analytic.
  const homeworldSectorOverlays = useMemo(
    () => data.regionOverlays.filter(isHomeworldSectorOverlay),
    [data.regionOverlays]
  )
  // Success (not merely !pending): failure-empty must not consume init-only ``all``.
  // Live frame only: retained prior-turn overlays must not consume ``all``.
  // Sole materialize-effect owner (Tile uses shared map-overlay observer + selection hook).
  useHomeworldRegionSelectionMaterialize(
    homeworldSectorOverlays,
    homeworldOverlaysReadyForMaterialize({
      homeworldEnabled,
      mapLayersPending,
      homeworldMapLayerSucceeded,
      displayMapFrameIsLive,
    })
  )
  // Shared store→effective indexes (same hook as sidebar selection).
  const { selectedSectorIndexes } = useEffectiveHomeworldSectorIndexes(
    homeworldSectorOverlays
  )

  // Raw homeworld sector overlays for ownership assert keying (independent of paint filter).
  const ownershipRegionOverlays = data.regionOverlays

  // Visibility prefs → region selection + envelope toggle → assert-focus.
  const regionOverlays = useMemo(
    () =>
      buildHomeworldRegionOverlaysForPaint({
        overlays: applyVisibilityRegionPreferences(
          data.regionOverlays,
          visibilityKinds
        ),
        effectiveSelectedSectorIndexes: selectedSectorIndexes,
        showEnvelopeOverlays,
        assertFocusSelection: selection,
        homeworldMarkers: data.homeworldMarkers,
      }),
    [
      data.regionOverlays,
      data.homeworldMarkers,
      visibilityKinds,
      selectedSectorIndexes,
      showEnvelopeOverlays,
      selection,
    ]
  )

  return (
    <FleetLocationRingStacksProvider stacks={fleetStacks}>
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      defaultViewport={{ x: 0, y: 0, zoom: 1 }}
      fitView={false}
      minZoom={MAP_ZOOM_MIN}
      maxZoom={MAP_ZOOM_MAX}
      proOptions={{ hideAttribution: true }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      panOnDrag
      zoomOnScroll
      zoomOnPinch
    >
      <InitialViewportFit
        nodes={frame.nodes}
        onInitialFitDone={onInitialFitDone}
        onMapZoomChange={onMapZoomChange}
      />
      <ViewportZoomSync onMapZoomChange={onMapZoomChange} />
      <SliderZoomControl onMapZoomChange={onMapZoomChange} onSetZoomReady={onSetZoomReady} />
      <MapZoomKeyboardShortcuts onMapZoomChange={onMapZoomChange} />
      <CoordinateGridOverlay />
      {cartography != null ? (
        <StellarCartographyOverlayPane
          overlayCircles={frame.overlayCircles}
          wormholeEndpoints={frame.wormholeEndpoints}
          cartographyConfig={cartography.config}
          wormholeEndpointHoverByCell={frame.wormholeEndpointHoverByCell}
          nuIonStorms={data.nuIonStorms}
        />
      ) : null}
      <MapRegionOverlayPane regionOverlays={regionOverlays} />
      <NormalWarpWellOutlinesOverlay mapNodes={planetMapNodes} />
      <HomeworldMarkersOverlay markers={data.homeworldMarkers} />
      <FleetLocationRingsOverlay stacks={fleetStacks} />
      <MapAttentionOrchestrator homeworldMarkers={data.homeworldMarkers} />
      <MapInteractionSurface>
        <PlanetMapInteraction
          planetGrid={planetGrid}
          planetLabelOptions={planetLabelOptions}
          labelSourceByNodeId={labelSourceByNodeId}
          mapNodes={planetMapNodes}
          waypointGrid={waypointGrid}
        >
          <FixedSizeDotsOverlay
            mapNodes={planetMapNodes}
            routeWaypoints={data.routeWaypoints}
          />
        </PlanetMapInteraction>
        <FleetMapInteractionContributor stacks={fleetStacks} enabled={fleetEnabled} />
        <RegionMapInteractionContributor regionOverlays={regionOverlays} />
        <CartographyMapInteractionContributor cartography={cartography} />
        <WormholeMapInteractionContributor
          cartography={cartography}
          hoverByCell={frame.wormholeEndpointHoverByCell}
          displayEdges={displayMapEdges}
        />
      </MapInteractionSurface>
      <FlowCoordinateReadout />
      <HomeworldMapContextMenu
        analyticScope={analyticScope}
        enabled={homeworldEnabled}
        ownershipRegionOverlays={ownershipRegionOverlays}
        homeworldMarkers={data.homeworldMarkers}
        planetGrid={planetGrid}
        planetMapNodes={planetMapNodes}
        roster={roster}
      />
    </ReactFlow>
    </FleetLocationRingStacksProvider>
  )
}
