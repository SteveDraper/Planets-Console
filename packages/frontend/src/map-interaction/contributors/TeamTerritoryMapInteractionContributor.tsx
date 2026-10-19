/**
 * Territory descriptive **map interaction contributor**.
 * Active only while the Territory analytic is enabled.
 */

import { useMemo } from 'react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import {
  playerTerritoryHoverLinesAtMapPoint,
  teamTerritoryHoverLinesAtMapPoint,
} from '../../analytics/team-information/teamTerritoryHover'
import { clientToFlowPosition } from '../../lib/mapFlowGeometry'
import { flowCenterToPlanet } from '../../lib/planetSpatialGrid'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import { useMapInteractionContributor } from '../useMapInteractionContributor'

export function TeamTerritoryMapInteractionContributor({
  regionOverlays,
  namesByLeagueTeamId,
  usernamesByPlayerId,
  byTeam,
  enabled,
}: {
  regionOverlays: readonly MapRegionOverlay[]
  namesByLeagueTeamId: ReadonlyMap<number, string | null>
  usernamesByPlayerId: ReadonlyMap<number, string>
  byTeam: boolean
  enabled: boolean
}) {
  const contributor = useMemo<MapInteractionContributor | null>(() => {
    if (!enabled || regionOverlays.length === 0) return null
    return {
      id: 'team-territory',
      role: 'team-territory',
      hitTest: (hit) => {
        const flow = clientToFlowPosition(
          hit.clientPos.x,
          hit.clientPos.y,
          hit.domNode,
          hit.transform
        )
        if (flow == null) return null
        const { px, py } = flowCenterToPlanet(flow.x, flow.y)
        const lines = byTeam
          ? teamTerritoryHoverLinesAtMapPoint(regionOverlays, px, py, namesByLeagueTeamId)
          : playerTerritoryHoverLinesAtMapPoint(regionOverlays, px, py, usernamesByPlayerId)
        if (lines.length === 0) return null
        return {
          id: 'team-territory',
          role: 'team-territory',
          kind: 'descriptive',
          title: 'Territory',
          placement: { mode: 'cursor' },
          blocks: [{ type: 'lines', lines }],
        }
      },
    }
  }, [byTeam, enabled, namesByLeagueTeamId, regionOverlays, usernamesByPlayerId])

  useMapInteractionContributor(contributor, [
    regionOverlays,
    namesByLeagueTeamId,
    usernamesByPlayerId,
    byTeam,
    enabled,
  ])
  return null
}
