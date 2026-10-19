import { create } from 'zustand'
import type { HoveredTerritory } from '../analytics/team-information/kinds'

type TeamInformationHighlightState = {
  /** Territory legend row under the pointer. Null when no row is hovered. */
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
