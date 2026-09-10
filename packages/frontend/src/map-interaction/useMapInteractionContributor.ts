/**
 * Register / unregister a **map interaction contributor** for the lifetime of
 * the calling component. Pass ``null`` when the analytic is disabled.
 *
 * ``revisionDeps`` is a ``useEffect``-style list: each element is compared with
 * ``Object.is``. Pass an inline list of inputs that should bump the registry
 * (so the hover engine recollects) even when id/role are unchanged. Do not pass
 * a single boxed value whose identity is new every render.
 */

import { useEffect, useRef } from 'react'
import type { MapInteractionContributor } from './mapInteractionContributorTypes'
import { useMapInteractionRegistry } from './mapInteractionRegistry'

const NO_REVISION_DEPS: readonly unknown[] = []

export function useMapInteractionContributor(
  contributor: MapInteractionContributor | null,
  revisionDeps: readonly unknown[] = NO_REVISION_DEPS
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
    // ``revisionDeps`` is caller-owned input identity, spread like ``useEffect``.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, role, hasFetch, hasSticky, register, unregister, ...revisionDeps])
}
