/**
 * Register / unregister a **map interaction contributor** for the lifetime of
 * the calling component. Pass ``null`` when the analytic is disabled.
 *
 * ``revision`` bumps the registry when contributor inputs change without an
 * id/role change (e.g. fleet stacks), so the hover engine recollects.
 */

import { useEffect, useRef } from 'react'
import type { MapInteractionContributor } from './mapInteractionContributorTypes'
import { useMapInteractionRegistry } from './mapInteractionRegistry'

export function useMapInteractionContributor(
  contributor: MapInteractionContributor | null,
  revision: unknown = 0
): void {
  const { register, unregister } = useMapInteractionRegistry()
  const latestRef = useRef(contributor)
  latestRef.current = contributor

  const id = contributor?.id ?? null
  const role = contributor?.role
  const hasFetch = contributor?.fetch != null
  const hasSticky = contributor?.stickyContribution != null

  useEffect(() => {
    if (id == null || role == null) return

    const wrapper: MapInteractionContributor = {
      id,
      role,
      hitTest: (hit) => latestRef.current?.hitTest(hit) ?? null,
      stickyContribution: hasSticky
        ? () => latestRef.current?.stickyContribution?.() ?? null
        : undefined,
      fetch: hasFetch
        ? (hit) => {
            const current = latestRef.current
            if (current?.fetch == null) {
              return Promise.resolve([])
            }
            return current.fetch(hit)
          }
        : undefined,
    }
    register(wrapper)
    return () => unregister(id)
  }, [id, role, hasFetch, hasSticky, register, unregister, revision])
}
