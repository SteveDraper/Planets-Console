/**
 * Analytic-agnostic map region overlay wire types.
 * Discriminated geometry: hybrid coverage (disks + nebula patches) or
 * closed boundary paths (line|arc edges). Distinct from Stellar Cartography
 * ``overlayCircles``.
 */

export type MapRegionCoverageRleRun = {
  length: number
  covered: boolean
}

export type MapRegionOverlayDisk = {
  x: number
  y: number
  radius: number
}

export type MapRegionOverlayPatch = {
  originX: number
  originY: number
  width: number
  height: number
  coverageRle: MapRegionCoverageRleRun[]
}

export type MapRegionOverlayVertex = {
  x: number
  y: number
}

export type MapRegionBoundaryLineEdge = {
  type: 'line'
}

export type MapRegionBoundaryArcEdge = {
  type: 'arc'
  centerX: number
  centerY: number
  /** Clockwise in map space (Y-up). Pane render flips for SVG Y-down. */
  clockwise: boolean
}

export type MapRegionBoundaryEdge = MapRegionBoundaryLineEdge | MapRegionBoundaryArcEdge

export type MapRegionCoverageGeometry = {
  type: 'coverage'
  disks: MapRegionOverlayDisk[]
  patches: MapRegionOverlayPatch[]
}

export type MapRegionBoundaryGeometry = {
  type: 'boundary'
  vertices: MapRegionOverlayVertex[]
  /** Edge i connects vertex i to vertex (i+1)%n (closed path). */
  edges: MapRegionBoundaryEdge[]
  /**
   * Optional envelope disks. When ``vertices``/``edges`` are empty, the overlay
   * is disks-only (no boundary outline) -- e.g. planet-centered homeworld envelopes.
   */
  disks?: MapRegionOverlayDisk[]
}

export type MapRegionOverlayGeometry = MapRegionCoverageGeometry | MapRegionBoundaryGeometry

/** Stroke style for one boundary envelope disk (index-aligned with geometry.disks). */
export type MapRegionDiskStrokePaint = {
  strokeColor: string
  strokeWidth: number
  strokeDasharray?: string
}

/**
 * Client-side paint policy for shared region blit.
 * Analytic style adapters attach this before ``buildMapRegionOverlayPaneShapes``;
 * Core wire does not emit ``paint``.
 */
export type MapRegionOverlayPaint = {
  fillOpacity: number
  strokeColor?: string
  strokeWidth?: number
  /**
   * When set, the boundary path is stroked with each entry (under to over).
   * Single-stroke overlays use ``strokeColor`` / ``strokeWidth`` instead.
   */
  boundaryStrokes?: readonly MapRegionDiskStrokePaint[]
  /**
   * When set, boundary geometry disks are stroke-outlined with these styles
   * instead of filled disks.
   */
  diskStrokes?: readonly MapRegionDiskStrokePaint[]
}

export type MapRegionPossibleOwner = {
  ownerSlot: number
  provenanceKinds: string[]
  /** Roster identity ``username (race)`` when Core resolved the slot. */
  playerLabel?: string
  /**
   * Per-kind ownership observation multiplicity (machine tags → counts).
   * Clients format hover copy; Core emits structured facts only.
   */
  provenanceKindCounts?: Record<string, number>
}

/**
 * Winning ownership strength class for a unique projected ``possibleOwners`` set
 * (ADR 0010). Omitted on the wire when ownership is ambiguous.
 */
export type OwnershipWinningStrength = 'weak' | 'strong' | 'asserted'

export type MapRegionOverlay = {
  kind: string
  id: string
  fillColor: string
  fillOpacity: number
  geometry: MapRegionOverlayGeometry
  isPinned?: boolean
  status?: string
  /** Domain fact: candidate planets in this region (homeworld sectors). */
  candidateCount?: number
  /** Roster identity for a pinned owner (e.g. ``username (race)``), not UI prose. */
  playerLabel?: string
  /** Ownership-evidence possible homeworld owners for this sector. */
  possibleOwners?: MapRegionPossibleOwner[]
  /**
   * Winning ownership strength for projected ``possibleOwners`` when ``|set|=1``.
   */
  ownershipWinningStrength?: OwnershipWinningStrength
  /** Optional client paint policy (analytic adapters; not Core wire). */
  paint?: MapRegionOverlayPaint
}
