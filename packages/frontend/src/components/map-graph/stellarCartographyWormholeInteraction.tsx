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
import { wormholeMapCellKey } from '../../lib/wormholeEndpointHover'

export type WormholeLineRevealApi = {
  revealAt: (mapX: number, mapY: number) => void
  scheduleClear: () => void
  cancelClear: () => void
}

export const WormholeHoverContext = createContext<(lines: string[] | null) => void>(() => {})

export const WORMHOLE_LINE_REVEAL_CLEAR_MS = 120

export const WormholeLineRevealContext = createContext<WormholeLineRevealApi>({
  revealAt: () => {},
  scheduleClear: () => {},
  cancelClear: () => {},
})

export type WormholeInteractionState = {
  wormholeLineRevealKey: string | null
  wormholeHoverLines: string[] | null
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
      blockedByPlanetHover,
      onPlanetLabelHoverActiveChange,
    }),
    [
      wormholeLineRevealKey,
      wormholeHoverLines,
      blockedByPlanetHover,
      onPlanetLabelHoverActiveChange,
    ]
  )

  return (
    <WormholeInteractionStateContext.Provider value={interactionState}>
      <WormholeHoverContext.Provider value={setWormholeHoverLines}>
        <WormholeLineRevealContext.Provider value={wormholeLineReveal}>
          {children}
        </WormholeLineRevealContext.Provider>
      </WormholeHoverContext.Provider>
    </WormholeInteractionStateContext.Provider>
  )
}
