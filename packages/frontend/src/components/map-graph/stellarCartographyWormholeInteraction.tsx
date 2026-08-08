/**
 * Wormhole on-hover line reveal state for Stellar Cartography paint.
 *
 * Hover *labels* are map-element contributions on the map interaction surface
 * (#293); this provider only owns which wormhole lines are revealed in
 * on-hover display mode.
 */

import {
  createContext,
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

export const WORMHOLE_LINE_REVEAL_CLEAR_MS = 120

export const WormholeLineRevealContext = createContext<WormholeLineRevealApi>({
  revealAt: () => {},
  scheduleClear: () => {},
  cancelClear: () => {},
})

export type WormholeInteractionState = {
  wormholeLineRevealKey: string | null
}

const WormholeInteractionStateContext = createContext<WormholeInteractionState | null>(
  null
)

export function useWormholeInteractionState(): WormholeInteractionState {
  const state = useContext(WormholeInteractionStateContext)
  if (state == null) {
    throw new Error(
      'useWormholeInteractionState must be used within WormholeInteractionProvider'
    )
  }
  return state
}

export function useWormholeLineReveal(): WormholeLineRevealApi {
  return useContext(WormholeLineRevealContext)
}

type WormholeInteractionProviderProps = {
  children: ReactNode
}

export function WormholeInteractionProvider({
  children,
}: WormholeInteractionProviderProps) {
  const [wormholeLineRevealKey, setWormholeLineRevealKey] = useState<string | null>(
    null
  )
  const wormholeLineRevealClearRef = useRef<ReturnType<typeof setTimeout> | null>(
    null
  )

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

  const interactionState = useMemo<WormholeInteractionState>(
    () => ({ wormholeLineRevealKey }),
    [wormholeLineRevealKey]
  )

  return (
    <WormholeInteractionStateContext.Provider value={interactionState}>
      <WormholeLineRevealContext.Provider value={wormholeLineReveal}>
        {children}
      </WormholeLineRevealContext.Provider>
    </WormholeInteractionStateContext.Provider>
  )
}
