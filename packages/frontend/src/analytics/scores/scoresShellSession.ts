import { createContext, useContext } from 'react'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import type { UseGlobalInferencePauseResult } from './useGlobalInferencePause'

export type ScoresShellSession = {
  inferenceByRow: ScoresInferenceRowDetail[] | undefined
  globalInferencePause: UseGlobalInferencePauseResult
}

export const ScoresShellStreamContext = createContext<ScoresShellSession | null>(null)

/** Shell session when the scoreboard stream is mounted above the table. */
export function useScoresShellStreamSession(): ScoresShellSession | null {
  return useContext(ScoresShellStreamContext)
}
