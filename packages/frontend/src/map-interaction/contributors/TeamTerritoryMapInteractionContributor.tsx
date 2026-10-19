/**
 * Territory descriptive **map interaction contributor**.
 * Active only while the Territory analytic is enabled.
 */

import { useMemo } from 'react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { territoryPartition } from '../../analytics/team-information/kinds'
import { territoryHoverLinesAtMapPoint } from '../../analytics/team-information/teamTerritoryHover'
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
  const partition = territoryPartition(byTeam)
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
        const lines = territoryHoverLinesAtMapPoint(
          regionOverlays,
          px,
          py,
          partition,
          namesByLeagueTeamId,
          usernamesByPlayerId
        )
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
  }, [enabled, namesByLeagueTeamId, partition, regionOverlays, usernamesByPlayerId])

  useMapInteractionContributor(contributor, [
    regionOverlays,
    namesByLeagueTeamId,
    usernamesByPlayerId,
    partition,
    enabled,
  ])
  return null
}
