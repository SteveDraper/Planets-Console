import { createContext, useContext, type ReactNode } from 'react'
import type { FleetPlayerStreamSlice } from './fleetTablePlayerStreamState'

const FleetStreamPlayersContext = createContext<Map<number, FleetPlayerStreamSlice> | null>(
  null
)

type FleetStreamPlayersProviderProps = {
  streamPlayersById: Map<number, FleetPlayerStreamSlice>
  children: ReactNode
}

/** Provides demuxed fleet stream slices owned above table/map view mode. */
export function FleetStreamPlayersProvider({
  streamPlayersById,
  children,
}: FleetStreamPlayersProviderProps) {
  return (
    <FleetStreamPlayersContext.Provider value={streamPlayersById}>
      {children}
    </FleetStreamPlayersContext.Provider>
  )
}

/** Shared fleet stream demux map; must render under FleetStreamPlayersProvider. */
export function useFleetStreamPlayersById(): Map<number, FleetPlayerStreamSlice> {
  const streamPlayersById = useContext(FleetStreamPlayersContext)
  if (streamPlayersById == null) {
    throw new Error('useFleetStreamPlayersById must be used within FleetStreamPlayersProvider')
  }
  return streamPlayersById
}
