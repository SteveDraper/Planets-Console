import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { ReactFlow } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import type { CombinedMapData, MapEdge } from '../api/bff'
import { STELLAR_CARTOGRAPHY_NODE_ID_PREFIX } from '../analytics/mapAnalyticIds'
import { StellarCartographyHoverPanel } from '../analytics/stellar-cartography/StellarCartographyHoverPanel'
import { filterWormholeEdgesForCartographyConfig } from '../analytics/stellar-cartography/overlayDisplayFilter'
import {
  buildWormholeEndpointHoverIndex,
} from '../lib/wormholeEndpointHover'
import {
  MAP_ZOOM_MAX,
  MAP_ZOOM_MIN,
} from '../lib/mapZoom'
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
import type { StellarCartographyMapUiConfig } from '../analytics/mapLayers'
import type { StellarCartographyMapUi } from './map-graph/stellarCartographyMapUi'
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

type MapGraphProps = {
  data: CombinedMapData
  className?: string
  onMapZoomChange: (zoom: number) => void
  /** Called once so the header slider can drive zoom (same as scroll wheel). */
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  planetLabelOptions?: PlanetLabelOptions
  cartographyActive: boolean
  cartographyConfig?: StellarCartographyMapUiConfig
  stellarCartography?: StellarCartographyMapUi
}

function displayMapNodes(
  nodes: CombinedMapData['nodes'],
  cartographyActive: boolean
): CombinedMapData['nodes'] {
  if (cartographyActive) return nodes
  return nodes.filter((node) => !node.id.startsWith(STELLAR_CARTOGRAPHY_NODE_ID_PREFIX))
}

function displayMapEdges(
  edges: CombinedMapData['edges'],
  cartographyActive: boolean
): CombinedMapData['edges'] {
  if (cartographyActive) return edges
  return edges.filter((edge) => edge.layer !== 'wormholes')
}

/** Max time to wait for initial viewport fit before showing the map anyway (avoids staying invisible if fit never runs). */
const INITIAL_FIT_REVEAL_MS = 250

export function MapGraph({
  data,
  className,
  onMapZoomChange,
  onSetZoomReady,
  planetLabelOptions = DEFAULT_PLANET_LABEL_OPTIONS,
  cartographyActive,
  cartographyConfig,
  stellarCartography,
}: MapGraphProps) {
  const [initialFitDone, setInitialFitDone] = useState(false)
  const onInitialFitDone = useCallback(() => setInitialFitDone(true), [])

  useEffect(() => {
    const t = setTimeout(() => setInitialFitDone(true), INITIAL_FIT_REVEAL_MS)
    return () => clearTimeout(t)
  }, [])

  const displayNodes = useMemo(
    () => displayMapNodes(data.nodes, cartographyActive),
    [data.nodes, cartographyActive]
  )
  const displayEdges = useMemo(
    () => displayMapEdges(data.edges, cartographyActive),
    [data.edges, cartographyActive]
  )
  const nodes = useMemo(() => toFlowNodes(displayNodes), [displayNodes])
  const planetMapNodes = useMemo(
    () => displayNodes.filter((n) => n.planet != null),
    [displayNodes]
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
    () =>
      cartographyActive
        ? collectWormholeEndpoints(displayNodes, data.wormholeUnknownEntrances)
        : [],
    [cartographyActive, displayNodes, data.wormholeUnknownEntrances]
  )
  const wormholeEndpointHoverByCell = useMemo(
    () =>
      cartographyActive
        ? buildWormholeEndpointHoverIndex(displayEdges, data.wormholeUnknownEntrances)
        : new Map(),
    [cartographyActive, displayEdges, data.wormholeUnknownEntrances]
  )

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
            displayNodes={displayNodes}
            displayEdges={displayEdges}
            nodes={nodes}
            planetMapNodes={planetMapNodes}
            planetGrid={planetGrid}
            waypointGrid={waypointGrid}
            labelSourceByNodeId={labelSourceByNodeId}
            wormholeEndpoints={wormholeEndpoints}
            wormholeEndpointHoverByCell={wormholeEndpointHoverByCell}
            planetLabelOptions={planetLabelOptions}
            cartographyActive={cartographyActive}
            cartographyConfig={cartographyConfig}
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
  displayNodes: CombinedMapData['nodes']
  displayEdges: MapEdge[]
  nodes: ReturnType<typeof toFlowNodes>
  planetMapNodes: CombinedMapData['nodes']
  planetGrid: ReturnType<typeof buildPlanetSpatialGrid>
  waypointGrid: ReturnType<typeof buildPlanetSpatialGrid> | null
  labelSourceByNodeId: ReturnType<typeof buildLabelSourceByNodeId>
  wormholeEndpoints: { x: number; y: number }[]
  wormholeEndpointHoverByCell: ReturnType<typeof buildWormholeEndpointHoverIndex>
  planetLabelOptions: PlanetLabelOptions
  cartographyActive: boolean
  cartographyConfig?: StellarCartographyMapUiConfig
  stellarCartography?: StellarCartographyMapUi
  onMapZoomChange: (zoom: number) => void
  onSetZoomReady: (setZoom: (zoom: number) => void) => void
  onInitialFitDone: () => void
}

function MapGraphFlow({
  data,
  displayNodes,
  displayEdges,
  nodes,
  planetMapNodes,
  planetGrid,
  waypointGrid,
  labelSourceByNodeId,
  wormholeEndpoints,
  wormholeEndpointHoverByCell,
  planetLabelOptions,
  cartographyActive,
  cartographyConfig,
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

  const visibleMapEdges = useMemo(() => {
    if (!cartographyActive || cartographyConfig == null) {
      return displayEdges
    }
    return filterWormholeEdgesForCartographyConfig(
      displayEdges,
      cartographyConfig,
      wormholeLineRevealKey
    )
  }, [cartographyActive, cartographyConfig, displayEdges, wormholeLineRevealKey])
  const edges = useMemo(() => toEdges(visibleMapEdges), [visibleMapEdges])

  return (
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
        nodes={displayNodes}
        onInitialFitDone={onInitialFitDone}
        onMapZoomChange={onMapZoomChange}
      />
      <ViewportZoomSync onMapZoomChange={onMapZoomChange} />
      <SliderZoomControl onMapZoomChange={onMapZoomChange} onSetZoomReady={onSetZoomReady} />
      <MapZoomKeyboardShortcuts onMapZoomChange={onMapZoomChange} />
      <CoordinateGridOverlay />
      {cartographyActive && cartographyConfig != null ? (
        <StellarCartographyOverlayPane
          overlayCircles={data.overlayCircles}
          wormholeEndpoints={wormholeEndpoints}
          cartographyConfig={cartographyConfig}
          wormholeEndpointHoverByCell={wormholeEndpointHoverByCell}
          wormholeRecenterPulseTarget={wormholeRecenterPulseTarget}
          blockedByPlanetHover={blockedByPlanetHover}
          nuIonStorms={data.nuIonStorms}
        />
      ) : null}
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
      {stellarCartography != null && cartographyConfig != null ? (
        <StellarCartographyHoverPanel
          analyticScope={stellarCartography.analyticScope}
          cartographyEnabled={stellarCartography.cartographyEnabled}
          cartographyConfig={cartographyConfig}
          wormholeHoverLines={wormholeHoverLines}
          blockedByPlanetHover={blockedByPlanetHover}
          clientToFlowPosition={clientToFlowPosition}
        />
      ) : null}
    </ReactFlow>
  )
}
