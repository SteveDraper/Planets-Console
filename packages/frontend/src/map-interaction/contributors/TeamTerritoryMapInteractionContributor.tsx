/**
 * Team territory descriptive **map interaction contributor**.
 * Active only while the Team information analytic is enabled.
 */

import { useMemo } from 'react'
import type { MapRegionOverlay } from '../../api/mapRegionOverlayTypes'
import { teamTerritoryHoverLinesAtMapPoint } from '../../analytics/team-information/teamTerritoryHover'
import { clientToFlowPosition } from '../../lib/mapFlowGeometry'
import { flowCenterToPlanet } from '../../lib/planetSpatialGrid'
import type { MapInteractionContributor } from '../mapInteractionContributorTypes'
import { useMapInteractionContributor } from '../useMapInteractionContributor'

export function TeamTerritoryMapInteractionContributor({
  regionOverlays,
  namesByLeagueTeamId,
  enabled,
}: {
  regionOverlays: readonly MapRegionOverlay[]
  namesByLeagueTeamId: ReadonlyMap<number, string | null>
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
        const lines = teamTerritoryHoverLinesAtMapPoint(
          regionOverlays,
          px,
          py,
          namesByLeagueTeamId
        )
        if (lines.length === 0) return null
        return {
          id: 'team-territory',
          role: 'team-territory',
          kind: 'descriptive',
          title: 'Team information',
          placement: { mode: 'cursor' },
          blocks: [{ type: 'lines', lines }],
        }
      },
    }
  }, [enabled, namesByLeagueTeamId, regionOverlays])

  useMapInteractionContributor(contributor, [regionOverlays, namesByLeagueTeamId, enabled])
  return null
}
