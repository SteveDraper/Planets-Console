import { useShellStore } from '../../stores/shell'
import { EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES } from '../stellar-cartography/layers'

export const FLEET_TEST_SHELL_PLAYERS = [
  { ordinal: 1, playerId: 8, name: 'Alice', raceName: null, eliminationTurn: null },
  { ordinal: 2, playerId: 9, name: 'Bob', raceName: null, eliminationTurn: null },
] as const

export type FleetTestViewpointOrdinal = (typeof FLEET_TEST_SHELL_PLAYERS)[number]['ordinal']

/** Seeds a selected viewpoint from storage-only slots (no BFF eligibility fetch). */
export function seedShellViewpoint(viewpointOrdinal: FleetTestViewpointOrdinal) {
  const stored = FLEET_TEST_SHELL_PLAYERS.map((player) => player.ordinal)
  useShellStore.setState({
    selectedGameId: '628580',
    gameInfoContext: {
      turn: 10,
      perspectives: [...FLEET_TEST_SHELL_PLAYERS],
      isGameFinished: true,
      sectorDisplayName: 'Test Sector',
      stellarCartographyGates: { ...EMPTY_STELLAR_CARTOGRAPHY_SETTINGS_GATES },
      homeworldInactiveReason: null,
    },
    selectedTurn: 5,
    perspectiveOverrideOrdinal: viewpointOrdinal,
    storageOnlyLoad: true,
    storageAvailablePerspectives: stored,
  })
}
