import { createContext, useContext } from 'react'
import type { ScoresInferenceRowDetail } from '../../api/bff'
import type { UseGlobalInferencePauseResult } from './useGlobalInferencePause'

export type ScoresShellSession = {
  inferenceByRow: ScoresInferenceRowDetail[] | undefined
  globalInferencePause: UseGlobalInferencePauseResult
}

export const ScoresShellStreamContext = createContext<ScoresShellSession | null>(null)

/** Scoreboard stream session; must render under ScoresShellStreamProvider. */
export function useScoresShellStreamSession(): ScoresShellSession {
  const session = useContext(ScoresShellStreamContext)
  if (session == null) {
    throw new Error('useScoresShellStreamSession must be used within ScoresShellStreamProvider')
  }
  return session
}
