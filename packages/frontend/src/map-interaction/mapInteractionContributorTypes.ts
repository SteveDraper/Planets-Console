/**
 * Registration contract for a **map interaction contributor** on the
 * **map interaction surface** (ADR 0012). Click / context-menu handlers share
 * this registration concept in a later slice; v1 is hover-only.
 */

import type {
  MapHoverContribution,
  MapHoverSyncBlock,
  MapInteractionContributorRole,
} from './mapHoverContributionTypes'
import type { MapPaneClientPos } from './useMapPanePointer'

/** Pane hit context produced by the surface for contributor hit-tests. */
export type MapHitContext = {
  clientPos: MapPaneClientPos
  /** Increments on each pane pointer move; async slots discard stale seq. */
  hitEpoch: number
  domNode: HTMLElement | null
  /** React Flow viewport transform ``[tx, ty, zoom]``. */
  transform: [number, number, number] | undefined
}

/**
 * Mount-scoped registration. Enable/disable should register/unregister so the
 * surface never queries disabled analytics.
 */
export type MapInteractionContributor = {
  id: string
  role: MapInteractionContributorRole
  /**
   * Sync hit-test for the current pointer. Return null when this contributor
   * has nothing under the hit. May include ``async`` pending blocks; the surface
   * fills them via ``fetch`` when present.
   */
  hitTest: (hit: MapHitContext) => MapHoverContribution | null
  /**
   * Optional manager-owned async path. Invoked when ``hitTest`` returns a
   * contribution with a pending ``async`` block; must be cancel-safe via
   * hitEpoch / requestKey (surface async slot).
   */
  fetch?: (hit: MapHitContext) => Promise<readonly MapHoverSyncBlock[]>
}
