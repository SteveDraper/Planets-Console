import type { AnalyticItem, AnalyticShellScope, ConnectionsMapParams } from '../api/bff'
import {
  BASE_MAP_ANALYTIC_ID,
  CONNECTIONS_ANALYTIC_ID,
  STELLAR_CARTOGRAPHY_ANALYTIC_ID,
} from '../analytics/mapAnalyticIds'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../analytics/stellar-cartography/layers'
import type { StellarCartographyMapUiConfig } from '../analytics/mapLayers'

export { BASE_MAP_ANALYTIC_ID, CONNECTIONS_ANALYTIC_ID, STELLAR_CARTOGRAPHY_ANALYTIC_ID }

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
  { id: BASE_MAP_ANALYTIC_ID, name: 'Base', supportsTable: false, supportsMap: true, type: 'base' },
  {
    id: CONNECTIONS_ANALYTIC_ID,
    name: 'Connections',
    supportsTable: true,
    supportsMap: true,
    type: 'selectable',
  },
  {
    id: STELLAR_CARTOGRAPHY_ANALYTIC_ID,
    name: 'Stellar Cartography',
    supportsTable: false,
    supportsMap: true,
    type: 'selectable',
  },
]

export const defaultStellarCartography: StellarCartographyMapUiConfig = {
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
