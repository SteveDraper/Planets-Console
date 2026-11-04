import type { ReactNode } from 'react'
import type { FleetAgeRefetchSession } from './useHomeworldFleetAgeRefetch'

/** Shell-lived mount. The poll hook does its work before this frame renders. */
export function HomeworldFleetAgeRefetchFrame({
  children,
}: FleetAgeRefetchSession & { children: ReactNode }) {
  return children
}
