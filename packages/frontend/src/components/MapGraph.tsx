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
  buildCartographyMapFrame,
  cartographyDisplayEdges,
  type CartographyMapFrame,
} from '../analytics/stellar-cartography/cartographyDisplayModel'
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
import { clientToFlowPosition } from './map-graph/geometry'
import { nodeTypes, toFlowNodes } from './map-graph/nodes'
import { edgeTypes, toEdges } from './map-graph/edges'
import { StellarCartographyOverlayPane } from './map-graph/StellarCartographyOverlayPane'
import {
  WormholeInteractionProvider,
  useWormholeInteractionState,
} from './map-graph/stellarCartographyWormholeInteraction'
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

  const frame = useMemo(
    () => buildCartographyMapFrame(data, cartography, futureTurnOffset),
    [data, cartography, futureTurnOffset]
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
        <WormholeInteractionProvider>
          <MapGraphFlow
            data={data}
            frame={frame}
            nodes={nodes}
            planetMapNodes={planetMapNodes}
            planetGrid={planetGrid}
            waypointGrid={waypointGrid}
            labelSourceByNodeId={labelSourceByNodeId}
            planetLabelOptions={planetLabelOptions}
            cartography={cartography}
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
  frame: CartographyMapFrame
  nodes: ReturnType<typeof toFlowNodes>
  planetMapNodes: CombinedMapData['nodes']
  planetGrid: ReturnType<typeof buildPlanetSpatialGrid>
  waypointGrid: ReturnType<typeof buildPlanetSpatialGrid> | null
  labelSourceByNodeId: ReturnType<typeof buildLabelSourceByNodeId>
  planetLabelOptions: PlanetLabelOptions
  cartography?: StellarCartographyMapContext
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
  cartography,
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

  const edges = useMemo(
    () => toEdges(cartographyDisplayEdges(frame, cartography, wormholeLineRevealKey)),
    [frame, cartography, wormholeLineRevealKey]
  )

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
      {cartography != null ? (
        <StellarCartographyHoverPanel
          cartography={cartography}
          wormholeHoverLines={wormholeHoverLines}
          blockedByPlanetHover={blockedByPlanetHover}
          clientToFlowPosition={clientToFlowPosition}
        />
      ) : null}
    </ReactFlow>
  )
}
