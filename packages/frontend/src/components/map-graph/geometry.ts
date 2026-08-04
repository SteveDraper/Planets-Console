/**
 * Re-exports map flow geometry for map-graph components.
 * Canonical home: `lib/mapFlowGeometry.ts` (analytics and other non-component callers import there).
 */
export {
  CELL_CENTER_OFFSET,
  NODE_SIZE_FLOW,
  clientToFlowPosition,
  flowCenterFromMapNode,
  flowPointNeedsPan,
  gameMapYToFlowCenterY,
  recenterViewportOnFlowPoint,
  safeZoomScale,
  type FlowViewportPane,
} from '../../lib/mapFlowGeometry'
