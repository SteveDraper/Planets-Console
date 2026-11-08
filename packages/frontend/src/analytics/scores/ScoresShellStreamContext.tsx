import type { ReactNode } from 'react'
import {
  ScoresShellStreamContext,
  type ScoresShellSession,
} from './scoresShellSession'

type ScoresShellStreamProviderProps = ScoresShellSession & {
  children: ReactNode
}

/** Shell-owned scoreboard inference session, shared across view modes. */
export function ScoresShellStreamProvider({
  inferenceByRow,
  globalInferencePause,
  children,
}: ScoresShellStreamProviderProps) {
  return (
    <ScoresShellStreamContext.Provider value={{ inferenceByRow, globalInferencePause }}>
      {children}
    </ScoresShellStreamContext.Provider>
  )
}
