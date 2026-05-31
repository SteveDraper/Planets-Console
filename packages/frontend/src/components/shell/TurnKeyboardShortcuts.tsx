import { useEffect } from 'react'
import { isModalDialogOpen, keyboardTargetBlocksShortcut } from '../../lib/keyboardShortcuts'

type TurnKeyboardShortcutsProps = {
  enabled: boolean
  stepTurn: (delta: number) => void
}

export function TurnKeyboardShortcuts({ enabled, stepTurn }: TurnKeyboardShortcutsProps) {
  useEffect(() => {
    if (!enabled) return

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key !== 'i' && e.key !== 'o') return
      if (keyboardTargetBlocksShortcut(e.target)) return
      if (isModalDialogOpen()) return
      e.preventDefault()
      stepTurn(e.key === 'i' ? -1 : 1)
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled, stepTurn])

  return null
}
