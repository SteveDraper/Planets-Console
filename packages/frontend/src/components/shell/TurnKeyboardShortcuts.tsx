import { useCallback } from 'react'
import { useWindowKeydown } from '../../lib/keyboardShortcuts'

type TurnKeyboardShortcutsProps = {
  enabled: boolean
  stepTurn: (delta: number) => void
}

export function TurnKeyboardShortcuts({ enabled, stepTurn }: TurnKeyboardShortcutsProps) {
  useWindowKeydown(
    useCallback(
      (e: KeyboardEvent) => {
        if (e.key !== 'i' && e.key !== 'o') return
        e.preventDefault()
        stepTurn(e.key === 'i' ? -1 : 1)
      },
      [stepTurn]
    ),
    { enabled }
  )

  return null
}
