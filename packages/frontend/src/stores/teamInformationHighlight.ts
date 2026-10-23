import { create } from 'zustand'
import type { HoveredTerritory } from '../analytics/team-information/kinds'

type TeamInformationHighlightState = {
  /** Legend name or color chip written by pointer movement. Null when unset or cleared. */
  hoveredTerritory: HoveredTerritory | null
  setHoveredTerritory: (hoveredTerritory: HoveredTerritory | null) => void
}

/** Ephemeral legend hover. Not persisted. */
export const useTeamInformationHighlightStore = create<TeamInformationHighlightState>()(
  (set) => ({
    hoveredTerritory: null,
    setHoveredTerritory: (hoveredTerritory) => set({ hoveredTerritory }),
  })
)
