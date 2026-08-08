import { useContext } from 'react'
import type { StellarCartographyOverlayWormholeMarkerShape } from '../../lib/cartography/stellarCartographyOverlay'
import { WormholeEndpointIconMark } from '../../lib/wormholeEndpointIcon'
import {
  formatWormholeEndpointHoverLines,
  type WormholeEndpointHoverInfo,
  wormholeEndpointRecenterGameCoords,
  wormholeMapCellKey,
} from '../../lib/wormholeEndpointHover'
import { isWormholeCellAttention } from '../../lib/mapAttention'
import {
  requestMapAttention,
  useMapAttentionRequestStore,
} from '../../stores/mapAttentionRequest'
import {
  WormholeHoverContext,
  WormholeLineRevealContext,
} from './stellarCartographyWormholeInteraction'

export function WormholeEndpointMarkers({
  markers,
  wormholeEndpointHoverByCell,
}: {
  markers: StellarCartographyOverlayWormholeMarkerShape[]
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
}) {
  const setWormholeHover = useContext(WormholeHoverContext)
  const lineReveal = useContext(WormholeLineRevealContext)
  const pending = useMapAttentionRequestStore((s) => s.pending)
  const pulseTarget = isWormholeCellAttention(pending) ? pending : null

  if (markers.length === 0) return null

  return (
    <div className="absolute inset-0" aria-hidden>
      {markers.map(({ key, cx, cy, diameterPx, mapX, mapY }) => {
        const half = diameterPx / 2
        const hoverInfo = wormholeEndpointHoverByCell.get(wormholeMapCellKey(mapX, mapY))
        const recenterGame =
          hoverInfo != null ? wormholeEndpointRecenterGameCoords(hoverInfo) : null
        const isPulseTarget =
          pulseTarget != null &&
          pulseTarget.mapX === mapX &&
          pulseTarget.mapY === mapY
        return (
          <div
            key={key}
            className={`absolute pointer-events-auto${recenterGame != null ? ' cursor-pointer' : ''}`}
            style={{
              left: cx - half,
              top: cy - half,
              width: diameterPx,
              height: diameterPx,
            }}
            onMouseEnter={() => {
              lineReveal.cancelClear()
              lineReveal.revealAt(mapX, mapY)
              if (hoverInfo == null) return
              setWormholeHover(formatWormholeEndpointHoverLines(hoverInfo))
            }}
            onMouseLeave={() => {
              setWormholeHover(null)
              lineReveal.scheduleClear()
            }}
            onClick={(e) => {
              if (recenterGame == null) return
              requestMapAttention({
                kind: 'wormhole-cell',
                mapX: recenterGame.x,
                mapY: recenterGame.y,
              })
              e.stopPropagation()
            }}
          >
            <div
              key={isPulseTarget ? `pulse-${pulseTarget.token}` : 'idle'}
              className={`h-full w-full${isPulseTarget ? ' wormhole-recenter-pulse' : ''}`}
            >
              <WormholeEndpointIconMark />
            </div>
          </div>
        )
      })}
    </div>
  )
}
