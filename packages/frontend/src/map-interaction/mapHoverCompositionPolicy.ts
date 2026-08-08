/**
 * **Map hover composition policy** for the **map interaction surface**
 * (ADR 0012 / CONTEXT glossary).
 *
 * Rules are keyed by contribution **kind** + contributor **role** -- not by
 * analytic id alone. ``yieldsTo`` suppresses; ``mergesWith`` folds descriptive
 * contributions into one host as titled sections; ``stacksWith`` keeps
 * independent chrome (map-element affordances).
 */

import type {
  MapHoverContribution,
  MapHoverContributionKind,
  MapHoverPlacement,
  MapInteractionContributorRole,
} from './mapHoverContributionTypes'

export type MapHoverCompositionRelation = 'yieldsTo' | 'mergesWith' | 'stacksWith'

export type MapHoverPolicyEndpoint = {
  kind: MapHoverContributionKind
  role: MapInteractionContributorRole
}

export type MapHoverPolicyEdge = {
  from: MapHoverPolicyEndpoint
  relation: MapHoverCompositionRelation
  to: MapHoverPolicyEndpoint
}

/**
 * v1 policy table (issue #292). Map-element / ``stacksWith`` machinery is
 * present so follow-on wormhole reclassification (#293) can attach without
 * inventing a second policy path.
 */
export const MAP_HOVER_COMPOSITION_POLICY: readonly MapHoverPolicyEdge[] = [
  {
    from: { kind: 'descriptive', role: 'region' },
    relation: 'yieldsTo',
    to: { kind: 'descriptive', role: 'planet' },
  },
  {
    from: { kind: 'descriptive', role: 'cartography' },
    relation: 'yieldsTo',
    to: { kind: 'descriptive', role: 'planet' },
  },
  {
    from: { kind: 'descriptive', role: 'wormhole' },
    relation: 'yieldsTo',
    to: { kind: 'descriptive', role: 'planet' },
  },
  {
    from: { kind: 'descriptive', role: 'fleet' },
    relation: 'mergesWith',
    to: { kind: 'descriptive', role: 'planet' },
  },
  {
    from: { kind: 'descriptive', role: 'region' },
    relation: 'mergesWith',
    to: { kind: 'descriptive', role: 'cartography' },
  },
  {
    from: { kind: 'descriptive', role: 'wormhole' },
    relation: 'mergesWith',
    to: { kind: 'descriptive', role: 'cartography' },
  },
]

/** Section order inside a merged descriptive host (cursor host by role order). */
export const DESCRIPTIVE_SECTION_ROLE_ORDER: readonly MapInteractionContributorRole[] =
  ['planet', 'fleet', 'region', 'cartography', 'wormhole']

export type ComposedDescriptiveSection = {
  contributionId: string
  role: MapInteractionContributorRole
  title: string
  blocks: MapHoverContribution['blocks']
}

export type ComposedDescriptiveHost = {
  /** Anchor wins if any section requests anchor; else cursor. */
  placement: MapHoverPlacement
  sections: readonly ComposedDescriptiveSection[]
}

export type MapHoverCompositionResult = {
  /** One or more descriptive hosts after yields + merges. */
  descriptiveHosts: readonly ComposedDescriptiveHost[]
  /** Map-element contributions that ``stacksWith`` descriptive chrome. */
  stacked: readonly MapHoverContribution[]
  /** Contribution ids suppressed by ``yieldsTo``. */
  suppressedIds: readonly string[]
}

function endpointKey(kind: MapHoverContributionKind, role: MapInteractionContributorRole): string {
  return `${kind}:${role}`
}

function contributionEndpointKey(c: MapHoverContribution): string {
  return endpointKey(c.kind, c.role)
}

function buildUndirectedMergePairs(
  edges: readonly MapHoverPolicyEdge[]
): ReadonlySet<string> {
  const pairs = new Set<string>()
  for (const edge of edges) {
    if (edge.relation !== 'mergesWith') continue
    const a = endpointKey(edge.from.kind, edge.from.role)
    const b = endpointKey(edge.to.kind, edge.to.role)
    pairs.add(a < b ? `${a}|${b}` : `${b}|${a}`)
  }
  return pairs
}

function yieldsToActive(
  contribution: MapHoverContribution,
  activeKeys: ReadonlySet<string>,
  edges: readonly MapHoverPolicyEdge[]
): boolean {
  for (const edge of edges) {
    if (edge.relation !== 'yieldsTo') continue
    if (
      edge.from.kind !== contribution.kind ||
      edge.from.role !== contribution.role
    ) {
      continue
    }
    if (activeKeys.has(endpointKey(edge.to.kind, edge.to.role))) {
      return true
    }
  }
  return false
}

function roleOrderIndex(role: MapInteractionContributorRole): number {
  const idx = DESCRIPTIVE_SECTION_ROLE_ORDER.indexOf(role)
  return idx === -1 ? DESCRIPTIVE_SECTION_ROLE_ORDER.length : idx
}

function sortSections(
  sections: ComposedDescriptiveSection[]
): ComposedDescriptiveSection[] {
  return [...sections].sort(
    (a, b) =>
      roleOrderIndex(a.role) - roleOrderIndex(b.role) ||
      a.contributionId.localeCompare(b.contributionId)
  )
}

/**
 * Choose host placement: any ``anchor`` request wins (prefer pinned, then
 * planet role, then first anchor); otherwise cursor.
 */
export function resolveDescriptiveHostPlacement(
  contributions: readonly MapHoverContribution[]
): MapHoverPlacement {
  const anchors = contributions.filter((c) => c.placement.mode === 'anchor')
  if (anchors.length === 0) {
    return { mode: 'cursor' }
  }
  const pinned = anchors.find(
    (c) => c.placement.mode === 'anchor' && c.placement.pinned === true
  )
  if (pinned) return pinned.placement
  const planet = anchors.find((c) => c.role === 'planet')
  if (planet) return planet.placement
  return anchors[0]!.placement
}

function mergePairKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`
}

/**
 * Connected components under undirected ``mergesWith`` among surviving
 * descriptive contributions.
 */
function mergeComponents(
  contributions: readonly MapHoverContribution[],
  mergePairs: ReadonlySet<string>
): MapHoverContribution[][] {
  const byKey = new Map<string, MapHoverContribution[]>()
  for (const c of contributions) {
    const key = contributionEndpointKey(c)
    const list = byKey.get(key)
    if (list) list.push(c)
    else byKey.set(key, [c])
  }

  const keys = [...byKey.keys()]
  const parent = new Map<string, string>()
  for (const k of keys) parent.set(k, k)

  function find(k: string): string {
    let cur = k
    while (parent.get(cur) !== cur) {
      cur = parent.get(cur)!
    }
    return cur
  }
  function union(a: string, b: string): void {
    const ra = find(a)
    const rb = find(b)
    if (ra !== rb) parent.set(ra, rb)
  }

  for (let i = 0; i < keys.length; i++) {
    for (let j = i + 1; j < keys.length; j++) {
      const a = keys[i]!
      const b = keys[j]!
      if (mergePairs.has(mergePairKey(a, b))) {
        union(a, b)
      }
    }
  }

  const groups = new Map<string, MapHoverContribution[]>()
  for (const k of keys) {
    const root = find(k)
    const members = byKey.get(k) ?? []
    const list = groups.get(root)
    if (list) list.push(...members)
    else groups.set(root, [...members])
  }
  return [...groups.values()]
}

/**
 * Compose simultaneous hits under the v1 **map hover composition policy**.
 */
export function composeMapHoverContributions(
  contributions: readonly MapHoverContribution[],
  policy: readonly MapHoverPolicyEdge[] = MAP_HOVER_COMPOSITION_POLICY
): MapHoverCompositionResult {
  const descriptive = contributions.filter((c) => c.kind === 'descriptive')
  const stacked = contributions.filter((c) => c.kind === 'map-element')

  const activeKeys = new Set(descriptive.map(contributionEndpointKey))
  const surviving: MapHoverContribution[] = []
  const suppressedIds: string[] = []

  for (const c of descriptive) {
    if (yieldsToActive(c, activeKeys, policy)) {
      suppressedIds.push(c.id)
      continue
    }
    surviving.push(c)
  }

  const mergePairs = buildUndirectedMergePairs(policy)
  const components = mergeComponents(surviving, mergePairs)

  const descriptiveHosts: ComposedDescriptiveHost[] = components.map(
    (group) => ({
      placement: resolveDescriptiveHostPlacement(group),
      sections: sortSections(
        group.map((c) => ({
          contributionId: c.id,
          role: c.role,
          title: c.title,
          blocks: c.blocks,
        }))
      ),
    })
  )

  // Stable host order: by first section role, then first contribution id.
  descriptiveHosts.sort((a, b) => {
    const aRole = a.sections[0]?.role
    const bRole = b.sections[0]?.role
    const roleCmp =
      roleOrderIndex(aRole ?? 'wormhole') - roleOrderIndex(bRole ?? 'wormhole')
    if (roleCmp !== 0) return roleCmp
    return (a.sections[0]?.contributionId ?? '').localeCompare(
      b.sections[0]?.contributionId ?? ''
    )
  })

  return { descriptiveHosts, stacked, suppressedIds }
}
