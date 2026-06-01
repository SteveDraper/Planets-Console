import type { ClusterOutlineDisplayMode } from './clusterOutlineDisplayMode'
import { isClusterCartographyActive } from './clusterOutlineDisplayMode'
import type { WormholeDisplayMode } from './wormholeDisplayMode'

/** Wire ids for persisted cartography layer toggles (match Core/BFF `layer` values). */
export type CartographyLayerId =
  | 'debris-disks'
  | 'star-clusters'
  | 'neutron-clusters'
  | 'nebulae'
  | 'ion-storms'
  | 'wormholes'
  | 'black-holes'

export const CARTOGRAPHY_LAYER_IDS: readonly CartographyLayerId[] = [
  'debris-disks',
  'star-clusters',
  'neutron-clusters',
  'nebulae',
  'ion-storms',
  'wormholes',
  'black-holes',
] as const

export type CartographyLayerDefinition = {
  id: CartographyLayerId
  label: string
  settingsGateKey: keyof StellarCartographySettingsGates
}

export const CARTOGRAPHY_LAYER_DEFINITIONS: readonly CartographyLayerDefinition[] = [
  { id: 'debris-disks', label: 'Debris disk borders', settingsGateKey: 'debrisDiskBorders' },
  { id: 'star-clusters', label: 'Star clusters', settingsGateKey: 'starClusters' },
  {
    id: 'neutron-clusters',
    label: 'Neutron clusters',
    settingsGateKey: 'neutronClusters',
  },
  { id: 'nebulae', label: 'Nebulae', settingsGateKey: 'nebulae' },
  { id: 'ion-storms', label: 'Ion storms', settingsGateKey: 'ionStorms' },
  { id: 'wormholes', label: 'Wormholes', settingsGateKey: 'wormholes' },
  { id: 'black-holes', label: 'Black holes', settingsGateKey: 'blackHoles' },
] as const

/** Game settings gates for which layer checkboxes may appear. */
export type StellarCartographySettingsGates = {
  debrisDiskBorders: boolean
  starClusters: boolean
  neutronClusters: boolean
  nebulae: boolean
  ionStorms: boolean
  wormholes: boolean
  blackHoles: boolean
}

export const EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES: StellarCartographySettingsGates = {
  debrisDiskBorders: false,
  starClusters: false,
  neutronClusters: false,
  nebulae: false,
  ionStorms: false,
  wormholes: false,
  blackHoles: false,
}

export type CartographyLayerVisibility = Record<
  Exclude<CartographyLayerId, 'wormholes' | 'star-clusters' | 'neutron-clusters'>,
  boolean
>

export function defaultCartographyLayerVisibility(): CartographyLayerVisibility {
  return {
    'debris-disks': true,
    nebulae: true,
    'ion-storms': true,
    'black-holes': true,
  }
}

export function isCartographyLayerGateEnabled(
  gates: StellarCartographySettingsGates,
  layerId: CartographyLayerId
): boolean {
  switch (layerId) {
    case 'debris-disks':
      return gates.debrisDiskBorders
    case 'star-clusters':
      return gates.starClusters
    case 'neutron-clusters':
      return gates.neutronClusters
    case 'nebulae':
      return gates.nebulae
    case 'ion-storms':
      return gates.ionStorms
    case 'wormholes':
      return gates.wormholes
    case 'black-holes':
      return gates.blackHoles
    default:
      return false
  }
}

/** Layer visibility inputs; {@link StellarCartographyMapUiConfig} in `mapUiConfig.ts` satisfies this shape. */
export type CartographyLayerShownOptions = {
  layerVisibility: CartographyLayerVisibility
  settingsGates: StellarCartographySettingsGates
  wormholeDisplayMode?: WormholeDisplayMode
  starClusterDisplayMode?: ClusterOutlineDisplayMode
  neutronClusterDisplayMode?: ClusterOutlineDisplayMode
}

export function isCartographyLayerShown(
  layerId: CartographyLayerId,
  {
    layerVisibility,
    settingsGates,
    wormholeDisplayMode,
    starClusterDisplayMode,
    neutronClusterDisplayMode,
  }: CartographyLayerShownOptions
): boolean {
  if (!isCartographyLayerGateEnabled(settingsGates, layerId)) return false
  if (layerId === 'wormholes') return wormholeDisplayMode == null || wormholeDisplayMode !== 'off'
  if (layerId === 'star-clusters') {
    return starClusterDisplayMode == null || isClusterCartographyActive(starClusterDisplayMode)
  }
  if (layerId === 'neutron-clusters') {
    return neutronClusterDisplayMode == null || isClusterCartographyActive(neutronClusterDisplayMode)
  }
  return layerVisibility[layerId] ?? true
}
