import type { CSSProperties } from 'react'
import { Handle, Position, type Node } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import {
  CELL_CENTER_OFFSET,
  NODE_SIZE_FLOW,
  gameMapYToFlowCenterY,
} from './geometry'

export type MapNodeData = {
  label?: string
  ordinal: number
  x: number
  y: number
  planet?: Record<string, unknown>
  ownerName?: string | null
}

/** Invisible handle at node center so edges connect to dot center. */
const centerHandleStyle: CSSProperties = {
  position: 'absolute',
  top: '50%',
  left: '50%',
  transform: 'translate(-50%, -50%)',
  opacity: 0,
  width: 12,
  height: 12,
  minWidth: 12,
  minHeight: 12,
  border: 'none',
  padding: 0,
  background: 'transparent',
  pointerEvents: 'none',
}

/** Invisible routing node; visible dot is drawn by the overlay. */
export function DotNode() {
  return (
    <div
      className="relative"
      style={{
        width: NODE_SIZE_FLOW,
        height: NODE_SIZE_FLOW,
        minWidth: NODE_SIZE_FLOW,
        minHeight: NODE_SIZE_FLOW,
      }}
    >
      <Handle type="target" position={Position.Left} id="t" style={centerHandleStyle} />
      <Handle type="source" position={Position.Left} id="s" style={centerHandleStyle} />
      {/* Planet labels are rendered in a separate overlay to keep pixel-stable positioning. */}
    </div>
  )
}

export const nodeTypes = { dot: DotNode }

/** Map coordinates (px, py) are cell indices; node geometry stays fixed and centered on the map cell. */
export function toFlowNodes(nodes: CombinedMapData['nodes']): Node<MapNodeData>[] {
  const half = NODE_SIZE_FLOW / 2
  return nodes.map((node, i) => {
    const x = Number(node.x)
    const y = Number(node.y)
    const px = Number.isFinite(x) ? x : 0
    const py = Number.isFinite(y) ? y : 0
    const cx = px + CELL_CENTER_OFFSET
    const cy = gameMapYToFlowCenterY(py)
    return {
      id: node.id,
      type: 'dot',
      position: { x: cx - half, y: cy - half },
      width: NODE_SIZE_FLOW,
      height: NODE_SIZE_FLOW,
      data: {
        label: node.label,
        ordinal: i + 1,
        x: px,
        y: py,
        planet: node.planet,
        ownerName: node.ownerName,
      },
    }
  })
}
