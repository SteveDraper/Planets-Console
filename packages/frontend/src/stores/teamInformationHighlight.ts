import { create } from 'zustand'

type TeamInformationHighlightState = {
  /** League team whose regions are outlined. Null when the legend is not hovered. */
  hoveredLeagueTeamId: number | null
  setHoveredLeagueTeamId: (hoveredLeagueTeamId: number | null) => void
}

/** Ephemeral legend hover. Not persisted. */
export const useTeamInformationHighlightStore = create<TeamInformationHighlightState>()(
  (set) => ({
    hoveredLeagueTeamId: null,
    setHoveredLeagueTeamId: (hoveredLeagueTeamId) => set({ hoveredLeagueTeamId }),
  })
)
