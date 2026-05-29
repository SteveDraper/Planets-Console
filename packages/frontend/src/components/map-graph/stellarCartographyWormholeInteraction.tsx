import { createContext } from 'react'
import { gameMapCellCenterToFlow } from '../../lib/stellarCartographyOverlay'
import { recenterViewportOnFlowPoint } from './geometry'

export type WormholeRecenterPulseTarget = {
  mapX: number
  mapY: number
  token: number
}

export type WormholeLineRevealApi = {
  revealAt: (mapX: number, mapY: number) => void
  scheduleClear: () => void
  cancelClear: () => void
}

export const WormholeHoverContext = createContext<(lines: string[] | null) => void>(() => {})

export const WormholeRecenterPulseContext = createContext<(mapX: number, mapY: number) => void>(
  () => {}
)

export const WORMHOLE_LINE_REVEAL_CLEAR_MS = 120

export const WormholeLineRevealContext = createContext<WormholeLineRevealApi>({
  revealAt: () => {},
  scheduleClear: () => {},
  cancelClear: () => {},
})

export function recenterMapOnWormholeGameCell(
  gameX: number,
  gameY: number,
  domNode: HTMLElement | null,
  getViewport: () => { x: number; y: number; zoom: number },
  setViewport: (vp: { x: number; y: number; zoom: number }) => void,
  pulseAt: (mapX: number, mapY: number) => void
): void {
  const { cx, cy } = gameMapCellCenterToFlow(gameX, gameY)
  recenterViewportOnFlowPoint(cx, cy, domNode, getViewport, setViewport)
  pulseAt(gameX, gameY)
}
