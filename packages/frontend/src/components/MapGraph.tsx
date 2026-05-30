import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { CombinedMapData } from '../api/bff'
import { StellarCartographyHoverPanel } from '../analytics/stellar-cartography/StellarCartographyHoverPanel'
import {
  filterWormholeEdgesForDisplayMode,
  type WormholeDisplayMode,
} from '../analytics/stellar-cartography/wormholeDisplayMode'
import {
  buildWormholeEndpointHoverIndex,
} from '../lib/wormholeEndpointHover'
import { buildPlanetSpatialGrid } from '../lib/planetSpatialGrid'
import {
  DEFAULT_PLANET_LABEL_OPTIONS,
  type PlanetLabelOptions,
} from './planetMapLabelModel'
import { clientToFlowPosition } from './map-graph/geometry'
import { nodeTypes, toFlowNodes } from './map-graph/nodes'
import { edgeTypes, toEdges } from './map-graph/edges'
import {
  StellarCartographyOverlayPane,
  collectWormholeEndpoints,
} from './map-graph/StellarCartographyOverlayPane'
import {
  WormholeInteractionProvider,
  useWormholeInteractionState,
} from './map-graph/stellarCartographyWormholeInteraction'
import type { StellarCartographyMapUi } from './map-graph/stellarCartographyMapUi'
import {
  buildLabelSourceByNodeId,
  FixedSizeDotsOverlay,
} from './map-graph/FixedSizeDotsOverlay'
import { CoordinateGridOverlay, FlowCoordinateReadout } from './map-graph/coordinateGrid'
import { NormalWarpWellOutlinesOverlay } from './map-graph/NormalWarpWellOutlinesOverlay'
import {
  InitialViewportFit,
  SliderZoomControl,
  ViewportZoomSync,
} from './map-graph/viewportControls'

type MapGraphProps = {
  data: CombinedMapData
  className?: string
  onMapZoomChange: (zoom: number) => void
  /** Called once so the header slider can drive zoom (same as scroll wheel). */
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  planetLabelOptions?: PlanetLabelOptions
  stellarCartography?: StellarCartographyMapUi
}

/** Max time to wait for initial viewport fit before showing the map anyway (avoids staying invisible if fit never runs). */
const INITIAL_FIT_REVEAL_MS = 250

const DEFAULT_WORMHOLE_DISPLAY_MODE: WormholeDisplayMode = 'always'

export function MapGraph({
  data,
  className,
  onMapZoomChange,
  onSetZoomReady,
  planetLabelOptions = DEFAULT_PLANET_LABEL_OPTIONS,
  stellarCartography,
}: MapGraphProps) {
  const [initialFitDone, setInitialFitDone] = useState(false)
  const onInitialFitDone = useCallback(() => setInitialFitDone(true), [])

  useEffect(() => {
    const t = setTimeout(() => setInitialFitDone(true), INITIAL_FIT_REVEAL_MS)
    return () => clearTimeout(t)
  }, [])

  const nodes = useMemo(() => toFlowNodes(data.nodes), [data.nodes])
  const planetMapNodes = useMemo(
    () => data.nodes.filter((n) => n.planet != null),
    [data.nodes]
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
  const wormholeEndpoints = useMemo(
    () => collectWormholeEndpoints(data.nodes, data.wormholeUnknownEntrances),
    [data.nodes, data.wormholeUnknownEntrances]
  )
  const wormholeEndpointHoverByCell = useMemo(
    () => buildWormholeEndpointHoverIndex(data.edges, data.wormholeUnknownEntrances),
    [data.edges, data.wormholeUnknownEntrances]
  )

  const wormholeDisplayMode =
    stellarCartography?.wormholeDisplayMode ?? DEFAULT_WORMHOLE_DISPLAY_MODE

  return (
    <div
      className={`map-graph-cursor-default relative min-h-0 overflow-hidden bg-black ${className ?? 'h-[320px] w-full min-w-0'}`}
    >
      <div
        className="h-full w-full transition-opacity duration-150"
        style={{ opacity: initialFitDone ? 1 : 0 }}
      >
        <WormholeInteractionProvider>
          <MapGraphFlow
            data={data}
            nodes={nodes}
            planetMapNodes={planetMapNodes}
            planetGrid={planetGrid}
            waypointGrid={waypointGrid}
            labelSourceByNodeId={labelSourceByNodeId}
            wormholeEndpoints={wormholeEndpoints}
            wormholeEndpointHoverByCell={wormholeEndpointHoverByCell}
            wormholeDisplayMode={wormholeDisplayMode}
            planetLabelOptions={planetLabelOptions}
            stellarCartography={stellarCartography}
            onMapZoomChange={onMapZoomChange}
            onSetZoomReady={onSetZoomReady}
            onInitialFitDone={onInitialFitDone}
          />
        </WormholeInteractionProvider>
      </div>
    </div>
  )
}

type MapGraphFlowProps = {
  data: CombinedMapData
  nodes: ReturnType<typeof toFlowNodes>
  planetMapNodes: CombinedMapData['nodes']
  planetGrid: ReturnType<typeof buildPlanetSpatialGrid>
  waypointGrid: ReturnType<typeof buildPlanetSpatialGrid> | null
  labelSourceByNodeId: ReturnType<typeof buildLabelSourceByNodeId>
  wormholeEndpoints: { x: number; y: number }[]
  wormholeEndpointHoverByCell: ReturnType<typeof buildWormholeEndpointHoverIndex>
  wormholeDisplayMode: WormholeDisplayMode
  planetLabelOptions: PlanetLabelOptions
  stellarCartography?: StellarCartographyMapUi
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  onInitialFitDone: () => void
}

function MapGraphFlow({
  data,
  nodes,
  planetMapNodes,
  planetGrid,
  waypointGrid,
  labelSourceByNodeId,
  wormholeEndpoints,
  wormholeEndpointHoverByCell,
  wormholeDisplayMode,
  planetLabelOptions,
  stellarCartography,
  onMapZoomChange,
  onSetZoomReady,
  onInitialFitDone,
}: MapGraphFlowProps) {
  const {
    wormholeLineRevealKey,
    wormholeHoverLines,
    wormholeRecenterPulseTarget,
    blockedByPlanetHover,
    onPlanetLabelHoverActiveChange,
  } = useWormholeInteractionState()

  const visibleMapEdges = useMemo(
    () =>
      filterWormholeEdgesForDisplayMode(
        data.edges,
        wormholeDisplayMode,
        wormholeLineRevealKey
      ),
    [data.edges, wormholeDisplayMode, wormholeLineRevealKey]
  )
  const edges = useMemo(() => toEdges(visibleMapEdges), [visibleMapEdges])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      defaultViewport={{ x: 0, y: 0, zoom: 1 }}
      fitView={false}
      minZoom={0.2}
      maxZoom={40}
      proOptions={{ hideAttribution: true }}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={false}
      panOnDrag
      zoomOnScroll
      zoomOnPinch
    >
      <InitialViewportFit
        nodes={data.nodes}
        onInitialFitDone={onInitialFitDone}
        onMapZoomChange={onMapZoomChange}
      />
      <ViewportZoomSync onMapZoomChange={onMapZoomChange} />
      <SliderZoomControl onMapZoomChange={onMapZoomChange} onSetZoomReady={onSetZoomReady} />
      <CoordinateGridOverlay />
      <StellarCartographyOverlayPane
        overlayCircles={data.overlayCircles}
        wormholeEndpoints={wormholeEndpoints}
        wormholeEndpointHoverByCell={wormholeEndpointHoverByCell}
        wormholeRecenterPulseTarget={wormholeRecenterPulseTarget}
        blockedByPlanetHover={blockedByPlanetHover}
        nuIonStorms={data.nuIonStorms}
      />
      <NormalWarpWellOutlinesOverlay mapNodes={planetMapNodes} />
      <FixedSizeDotsOverlay
        planetGrid={planetGrid}
        planetLabelOptions={planetLabelOptions}
        labelSourceByNodeId={labelSourceByNodeId}
        mapNodes={planetMapNodes}
        routeWaypoints={data.routeWaypoints}
        waypointGrid={waypointGrid}
        onPlanetLabelHoverActiveChange={onPlanetLabelHoverActiveChange}
      />
      <FlowCoordinateReadout />
      {stellarCartography != null ? (
        <StellarCartographyHoverPanel
          analyticScope={stellarCartography.analyticScope}
          sampleEnabled={stellarCartography.sampleEnabled}
          layerVisibility={stellarCartography.layerVisibility}
          settingsGates={stellarCartography.settingsGates}
          wormholeDisplayMode={stellarCartography.wormholeDisplayMode}
          starClusterDisplayMode={stellarCartography.starClusterDisplayMode}
          neutronClusterDisplayMode={stellarCartography.neutronClusterDisplayMode}
          wormholeHoverLines={wormholeHoverLines}
          blockedByPlanetHover={blockedByPlanetHover}
          clientToFlowPosition={clientToFlowPosition}
        />
      ) : null}
    </ReactFlow>
  )
}
