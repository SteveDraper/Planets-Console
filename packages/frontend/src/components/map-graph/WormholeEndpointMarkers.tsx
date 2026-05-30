import { useContext } from 'react'
import { useReactFlow, useStore } from '@xyflow/react'
import type { StellarCartographyOverlayWormholeMarkerShape } from '../../lib/cartography/stellarCartographyOverlay'
import { WormholeEndpointIconMark } from '../../lib/wormholeEndpointIcon'
import {
  formatWormholeEndpointHoverLines,
  type WormholeEndpointHoverInfo,
  wormholeEndpointRecenterGameCoords,
  wormholeMapCellKey,
} from '../../lib/wormholeEndpointHover'
import {
  WormholeHoverContext,
  WormholeLineRevealContext,
  WormholeRecenterPulseContext,
  type WormholeRecenterPulseTarget,
  recenterMapOnWormholeGameCell,
} from './stellarCartographyWormholeInteraction'

export function WormholeEndpointMarkers({
  markers,
  wormholeEndpointHoverByCell,
  wormholeRecenterPulseTarget,
  blockedByPlanetHover,
}: {
  markers: StellarCartographyOverlayWormholeMarkerShape[]
  wormholeEndpointHoverByCell: Map<string, WormholeEndpointHoverInfo>
  wormholeRecenterPulseTarget: WormholeRecenterPulseTarget | null
  blockedByPlanetHover: boolean
}) {
  const { setViewport, getViewport } = useReactFlow()
  const setWormholeHover = useContext(WormholeHoverContext)
  const pulseWormholeAt = useContext(WormholeRecenterPulseContext)
  const lineReveal = useContext(WormholeLineRevealContext)
  const domNode = useStore((s) => s.domNode ?? null)

  if (markers.length === 0) return null

  return (
    <div className="absolute inset-0" aria-hidden>
      {markers.map(({ key, cx, cy, diameterPx, mapX, mapY }) => {
        const half = diameterPx / 2
        const hoverInfo = wormholeEndpointHoverByCell.get(wormholeMapCellKey(mapX, mapY))
        const recenterGame =
          hoverInfo != null ? wormholeEndpointRecenterGameCoords(hoverInfo) : null
        const isPulseTarget =
          wormholeRecenterPulseTarget != null &&
          wormholeRecenterPulseTarget.mapX === mapX &&
          wormholeRecenterPulseTarget.mapY === mapY
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
              if (blockedByPlanetHover || hoverInfo == null) return
              setWormholeHover(formatWormholeEndpointHoverLines(hoverInfo))
            }}
            onMouseLeave={() => {
              setWormholeHover(null)
              lineReveal.scheduleClear()
            }}
            onClick={(e) => {
              if (recenterGame == null) return
              recenterMapOnWormholeGameCell(
                recenterGame.x,
                recenterGame.y,
                domNode,
                getViewport,
                setViewport,
                pulseWormholeAt
              )
              e.stopPropagation()
            }}
          >
            <div
              key={isPulseTarget ? `pulse-${wormholeRecenterPulseTarget.token}` : 'idle'}
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
