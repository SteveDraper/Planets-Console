/**
 * Mount-scoped registry for **map interaction contributor**s on the
 * **map interaction surface** (ADR 0012).
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import type { MapInteractionContributor } from './mapInteractionContributorTypes'
import type { MapHitContext } from './mapInteractionContributorTypes'
import type { MapPaneClientPos } from './useMapPanePointer'

export type MapInteractionHitState = {
  clientPos: MapPaneClientPos | null
  hitEpoch: number
  domNode: HTMLElement | null
  transform: [number, number, number] | undefined
}

export type MapInteractionRegistryApi = {
  register: (contributor: MapInteractionContributor) => void
  unregister: (id: string) => void
  /** Snapshot of registered contributors (stable until next register/unregister). */
  list: () => readonly MapInteractionContributor[]
  /** Subscribe to registry version bumps (for surface re-render). */
  version: number
}

const RegistryContext = createContext<MapInteractionRegistryApi | null>(null)
const HitStateContext = createContext<MapInteractionHitState | null>(null)

export function useMapInteractionRegistry(): MapInteractionRegistryApi {
  const api = useContext(RegistryContext)
  if (api == null) {
    throw new Error('useMapInteractionRegistry must be used within MapInteractionSurface')
  }
  return api
}

/** Pane hit state for paint helpers (e.g. waypoint hover) that share the surface pointer. */
export function useMapInteractionHitState(): MapInteractionHitState {
  const state = useContext(HitStateContext)
  if (state == null) {
    throw new Error('useMapInteractionHitState must be used within MapInteractionSurface')
  }
  return state
}

export function useOptionalMapInteractionHitState(): MapInteractionHitState | null {
  return useContext(HitStateContext)
}

type MapInteractionRegistryProviderProps = {
  children: ReactNode
  hit: MapInteractionHitState
}

export function MapInteractionRegistryProvider({
  children,
  hit,
}: MapInteractionRegistryProviderProps) {
  const contributorsRef = useRef(new Map<string, MapInteractionContributor>())
  const [version, setVersion] = useState(0)

  const register = useCallback((contributor: MapInteractionContributor) => {
    contributorsRef.current.set(contributor.id, contributor)
    setVersion((v) => v + 1)
  }, [])

  const unregister = useCallback((id: string) => {
    if (!contributorsRef.current.delete(id)) return
    setVersion((v) => v + 1)
  }, [])

  const list = useCallback(() => [...contributorsRef.current.values()], [])

  const api = useMemo<MapInteractionRegistryApi>(
    () => ({ register, unregister, list, version }),
    [register, unregister, list, version]
  )

  return (
    <RegistryContext.Provider value={api}>
      <HitStateContext.Provider value={hit}>{children}</HitStateContext.Provider>
    </RegistryContext.Provider>
  )
}

/** Build a ``MapHitContext`` when the pointer is over the pane; otherwise null. */
export function mapHitContextFromState(
  hit: MapInteractionHitState
): MapHitContext | null {
  if (hit.clientPos == null) return null
  return {
    clientPos: hit.clientPos,
    hitEpoch: hit.hitEpoch,
    domNode: hit.domNode,
    transform: hit.transform,
  }
}
