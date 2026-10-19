import { create } from 'zustand'

type TeamInformationHighlightState = {
  /** League team whose regions are outlined. Null when that legend is not hovered. */
  hoveredLeagueTeamId: number | null
  /** Player whose regions are outlined. Null when that legend is not hovered. */
  hoveredPlayerId: number | null
  setHoveredLeagueTeamId: (hoveredLeagueTeamId: number | null) => void
  setHoveredPlayerId: (hoveredPlayerId: number | null) => void
}

/** Ephemeral legend hover. Not persisted. */
export const useTeamInformationHighlightStore = create<TeamInformationHighlightState>()(
  (set) => ({
    hoveredLeagueTeamId: null,
    hoveredPlayerId: null,
    setHoveredLeagueTeamId: (hoveredLeagueTeamId) => set({ hoveredLeagueTeamId }),
    setHoveredPlayerId: (hoveredPlayerId) => set({ hoveredPlayerId }),
  })
)
