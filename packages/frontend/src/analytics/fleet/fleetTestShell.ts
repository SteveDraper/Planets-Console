import { useShellStore } from '../../stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'

export const FLEET_TEST_SHELL_PLAYERS = [
  { ordinal: 1, playerId: 8, name: 'Alice', raceName: null },
  { ordinal: 2, playerId: 9, name: 'Bob', raceName: null },
] as const

export type FleetTestViewpointName = (typeof FLEET_TEST_SHELL_PLAYERS)[number]['name']

export function seedShellViewpoint(viewpointName: FleetTestViewpointName) {
  useShellStore.setState({
    selectedGameId: '628580',
    gameInfoContext: {
      turn: 10,
      perspectives: [...FLEET_TEST_SHELL_PLAYERS],
      isGameFinished: true,
      sectorDisplayName: 'Test Sector',
      stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
    },
    selectedTurn: 5,
    perspectiveOverrideName: viewpointName,
    storageOnlyLoad: false,
    storageAvailablePerspectives: null,
  })
}
