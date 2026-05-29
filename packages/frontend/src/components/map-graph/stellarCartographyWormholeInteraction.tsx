import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { gameMapCellCenterToFlow } from '../../lib/cartography/cartographyOverlayGeometry'
import { WORMHOLE_RECENTER_PULSE_MS } from '../../lib/cartography/stellarCartographyTheme'
import { wormholeMapCellKey } from '../../lib/wormholeEndpointHover'
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

export type WormholeInteractionState = {
  wormholeLineRevealKey: string | null
  wormholeHoverLines: string[] | null
  wormholeRecenterPulseTarget: WormholeRecenterPulseTarget | null
  blockedByPlanetHover: boolean
  onPlanetLabelHoverActiveChange: (active: boolean) => void
}

const WormholeInteractionStateContext = createContext<WormholeInteractionState | null>(null)

export function useWormholeInteractionState(): WormholeInteractionState {
  const state = useContext(WormholeInteractionStateContext)
  if (state == null) {
    throw new Error('useWormholeInteractionState must be used within WormholeInteractionProvider')
  }
  return state
}

type WormholeInteractionProviderProps = {
  children: ReactNode
  /** When set, overrides internal planet-label hover blocking (e.g. tests). */
  blockedByPlanetHover?: boolean
}

export function WormholeInteractionProvider({
  children,
  blockedByPlanetHover: blockedByPlanetHoverProp,
}: WormholeInteractionProviderProps) {
  const [wormholeHoverLines, setWormholeHoverLines] = useState<string[] | null>(null)
  const [wormholeRecenterPulseTarget, setWormholeRecenterPulseTarget] =
    useState<WormholeRecenterPulseTarget | null>(null)
  const [wormholeLineRevealKey, setWormholeLineRevealKey] = useState<string | null>(null)
  const wormholeLineRevealClearRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [planetLabelHoverActive, setPlanetLabelHoverActive] = useState(false)

  const wormholeLineReveal = useMemo<WormholeLineRevealApi>(
    () => ({
      revealAt: (mapX, mapY) => {
        if (wormholeLineRevealClearRef.current != null) {
          clearTimeout(wormholeLineRevealClearRef.current)
          wormholeLineRevealClearRef.current = null
        }
        setWormholeLineRevealKey(wormholeMapCellKey(mapX, mapY))
      },
      scheduleClear: () => {
        if (wormholeLineRevealClearRef.current != null) {
          clearTimeout(wormholeLineRevealClearRef.current)
        }
        wormholeLineRevealClearRef.current = setTimeout(() => {
          wormholeLineRevealClearRef.current = null
          setWormholeLineRevealKey(null)
        }, WORMHOLE_LINE_REVEAL_CLEAR_MS)
      },
      cancelClear: () => {
        if (wormholeLineRevealClearRef.current != null) {
          clearTimeout(wormholeLineRevealClearRef.current)
          wormholeLineRevealClearRef.current = null
        }
      },
    }),
    []
  )

  useEffect(() => {
    return () => {
      if (wormholeLineRevealClearRef.current != null) {
        clearTimeout(wormholeLineRevealClearRef.current)
      }
    }
  }, [])

  const pulseWormholeAt = useCallback((mapX: number, mapY: number) => {
    setWormholeRecenterPulseTarget({ mapX, mapY, token: Date.now() })
  }, [])

  useEffect(() => {
    if (wormholeRecenterPulseTarget == null) return
    const t = setTimeout(() => setWormholeRecenterPulseTarget(null), WORMHOLE_RECENTER_PULSE_MS)
    return () => clearTimeout(t)
  }, [wormholeRecenterPulseTarget])

  const onPlanetLabelHoverActiveChange = useCallback((active: boolean) => {
    setPlanetLabelHoverActive(active)
    if (active) setWormholeHoverLines(null)
  }, [])

  const blockedByPlanetHover =
    blockedByPlanetHoverProp ?? planetLabelHoverActive

  const interactionState = useMemo<WormholeInteractionState>(
    () => ({
      wormholeLineRevealKey,
      wormholeHoverLines,
      wormholeRecenterPulseTarget,
      blockedByPlanetHover,
      onPlanetLabelHoverActiveChange,
    }),
    [
      wormholeLineRevealKey,
      wormholeHoverLines,
      wormholeRecenterPulseTarget,
      blockedByPlanetHover,
      onPlanetLabelHoverActiveChange,
    ]
  )

  return (
    <WormholeInteractionStateContext.Provider value={interactionState}>
      <WormholeHoverContext.Provider value={setWormholeHoverLines}>
        <WormholeLineRevealContext.Provider value={wormholeLineReveal}>
          <WormholeRecenterPulseContext.Provider value={pulseWormholeAt}>
            {children}
          </WormholeRecenterPulseContext.Provider>
        </WormholeLineRevealContext.Provider>
      </WormholeHoverContext.Provider>
    </WormholeInteractionStateContext.Provider>
  )
}

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
