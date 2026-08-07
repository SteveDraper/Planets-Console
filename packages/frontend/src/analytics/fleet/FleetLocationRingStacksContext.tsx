import { createContext, useContext, useMemo, type ReactNode } from 'react'
import {
  fleetLocationRingStackKey,
  type FleetLocationRingStack,
} from './fleetLocationRings'

const FleetLocationRingStacksContext = createContext<readonly FleetLocationRingStack[]>(
  []
)

type FleetLocationRingStacksProviderProps = {
  stacks: readonly FleetLocationRingStack[]
  children: ReactNode
}

/** Shares computed location-ring stacks with map paint and planet-label hover. */
export function FleetLocationRingStacksProvider({
  stacks,
  children,
}: FleetLocationRingStacksProviderProps) {
  return (
    <FleetLocationRingStacksContext.Provider value={stacks}>
      {children}
    </FleetLocationRingStacksContext.Provider>
  )
}

export function useFleetLocationRingStacksFromContext(): readonly FleetLocationRingStack[] {
  return useContext(FleetLocationRingStacksContext)
}

/** Exact-coordinate stack lookup for planet labels at a map cell. */
export function useFleetLocationRingStackAt(
  x: number,
  y: number
): FleetLocationRingStack | null {
  const stacks = useContext(FleetLocationRingStacksContext)
  const key = fleetLocationRingStackKey(x, y)
  return useMemo(() => stacks.find((stack) => stack.key === key) ?? null, [stacks, key])
}
