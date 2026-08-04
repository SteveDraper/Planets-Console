/**
 * Ephemeral flash token for homeworld candidate map markers (panel click → pulse).
 */

import { create } from 'zustand'

export type HomeworldCandidateFlashTarget = {
  planetId: number
  token: number
}

type HomeworldCandidateFlashState = {
  flashTarget: HomeworldCandidateFlashTarget | null
  flashPlanet: (planetId: number) => void
  clearFlash: () => void
}

export const useHomeworldCandidateFlashStore = create<HomeworldCandidateFlashState>()(
  (set) => ({
    flashTarget: null,
    flashPlanet: (planetId) =>
      set({ flashTarget: { planetId, token: Date.now() } }),
    clearFlash: () => set({ flashTarget: null }),
  })
)
