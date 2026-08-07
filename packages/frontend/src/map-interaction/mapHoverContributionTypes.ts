/**
 * Typed payloads for the **map interaction surface** (ADR 0012 / CONTEXT glossary).
 *
 * Contributions are classified by **map hover contribution kind**; composition is
 * driven by ``mapHoverCompositionPolicy``, not by analytic-private flags.
 */

import type { ReactNode } from 'react'

/** Classification for **map hover composition policy**. */
export type MapHoverContributionKind = 'descriptive' | 'map-element'

/**
 * Mount-scoped contributor role. Policy edges and section order use roles;
 * analytic ids alone are not the composition key.
 */
export type MapInteractionContributorRole =
  | 'planet'
  | 'fleet'
  | 'region'
  | 'cartography'
  | 'wormhole'

/** Cursor-follow vs map-anchored (+ optional pin) host placement. */
export type MapHoverPlacement =
  | { mode: 'cursor' }
  | {
      mode: 'anchor'
      /** Flow-space anchor point (dot / ring center). */
      flowX: number
      flowY: number
      /** When true, host stays until explicitly cleared (planet pin). */
      pinned?: boolean
    }

export type MapHoverLinesBlock = {
  type: 'lines'
  lines: readonly string[]
}

export type MapHoverRichBlock = {
  type: 'rich'
  /** Opaque to the composer; rendered by surface chrome. */
  content: ReactNode
}

export type MapHoverSyncBlock = MapHoverLinesBlock | MapHoverRichBlock

/**
 * Async sample slot payload. The surface owns debounce / cancel / stale-seq;
 * contributors supply ``fetch(hit) → sync blocks`` (see contributor types).
 */
export type MapHoverAsyncBlock = {
  type: 'async'
  /** Stable key for the in-flight sample (e.g. cartography map cell). */
  requestKey: string
  status: 'pending' | 'ready' | 'error'
  /** Present when ``status`` is ``ready``. */
  blocks?: readonly MapHoverSyncBlock[]
  errorMessage?: string
}

export type MapHoverBlock = MapHoverSyncBlock | MapHoverAsyncBlock

/** One hit payload from a **map interaction contributor**. */
export type MapHoverContribution = {
  /** Stable id for suppress / merge bookkeeping (typically role + hit key). */
  id: string
  role: MapInteractionContributorRole
  kind: MapHoverContributionKind
  /** Section title when folded into a descriptive host. */
  title: string
  placement: MapHoverPlacement
  blocks: readonly MapHoverBlock[]
}
