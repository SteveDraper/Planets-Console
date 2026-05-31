import type { AnalyticItem, AnalyticShellScope, ConnectionsMapParams } from '../api/bff'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import type { StellarCartographyMapMergeOptions } from '../analytics/mapLayers'

export const defaultConnectionsParams: ConnectionsMapParams = {
  warpSpeed: 9,
  gravitonicMovement: false,
  flareMode: 'off',
  flareDepth: 2,
}

export const sampleScope: AnalyticShellScope = {
  gameId: '628580',
  turn: 5,
  perspective: 1,
}

export const sampleAnalytics: AnalyticItem[] = [
  { id: 'base-map', name: 'Base', supportsTable: false, supportsMap: true, type: 'base' },
  {
    id: 'connections',
    name: 'Connections',
    supportsTable: true,
    supportsMap: true,
    type: 'selectable',
  },
  {
    id: 'stellar-cartography',
    name: 'Stellar Cartography',
    supportsTable: false,
    supportsMap: true,
    type: 'selectable',
  },
]

export const defaultStellarCartography: StellarCartographyMapMergeOptions = {
  layerVisibility: {
    'debris-disks': true,
    nebulae: true,
    'ion-storms': true,
    'black-holes': true,
  },
  settingsGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
  wormholeDisplayMode: 'off',
  starClusterDisplayMode: 'off',
  neutronClusterDisplayMode: 'off',
}
