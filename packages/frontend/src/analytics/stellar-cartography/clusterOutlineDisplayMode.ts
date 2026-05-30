/** Three-state visibility for star and neutron cluster map overlays. */
export type ClusterOutlineDisplayMode = 'off' | 'no-outline' | 'outlined'

export const CLUSTER_OUTLINE_DISPLAY_MODE_LABELS: Record<ClusterOutlineDisplayMode, string> = {
  off: 'Off',
  'no-outline': 'No outline',
  outlined: 'Outlined',
}

export const CLUSTER_OUTLINE_DISPLAY_MODES: readonly ClusterOutlineDisplayMode[] = [
  'off',
  'no-outline',
  'outlined',
] as const

export function defaultStarClusterDisplayMode(): ClusterOutlineDisplayMode {
  return 'outlined'
}

export function defaultNeutronClusterDisplayMode(): ClusterOutlineDisplayMode {
  return 'outlined'
}

export function isClusterCartographyActive(mode: ClusterOutlineDisplayMode): boolean {
  return mode !== 'off'
}

export function areClusterOutlinesShown(mode: ClusterOutlineDisplayMode): boolean {
  return mode === 'outlined'
}

export function migratePersistedClusterLayers(
  layers: Record<string, unknown> | undefined,
  starClusterDisplayMode: ClusterOutlineDisplayMode | undefined,
  neutronClusterDisplayMode: ClusterOutlineDisplayMode | undefined
): {
  layers: Record<string, unknown>
  starClusterDisplayMode: ClusterOutlineDisplayMode
  neutronClusterDisplayMode: ClusterOutlineDisplayMode
} {
  const nextLayers = { ...(layers ?? {}) }
  let starMode = starClusterDisplayMode
  let neutronMode = neutronClusterDisplayMode
  if ('star-clusters' in nextLayers) {
    const legacy = nextLayers['star-clusters']
    if (starMode == null) {
      starMode = legacy === false ? 'off' : 'outlined'
    }
    delete nextLayers['star-clusters']
  }
  if ('neutron-clusters' in nextLayers) {
    const legacy = nextLayers['neutron-clusters']
    if (neutronMode == null) {
      neutronMode = legacy === false ? 'off' : 'outlined'
    }
    delete nextLayers['neutron-clusters']
  }
  return {
    layers: nextLayers,
    starClusterDisplayMode: starMode ?? defaultStarClusterDisplayMode(),
    neutronClusterDisplayMode: neutronMode ?? defaultNeutronClusterDisplayMode(),
  }
}
