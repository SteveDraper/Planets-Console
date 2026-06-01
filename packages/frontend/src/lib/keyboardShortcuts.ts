import { useEffect } from 'react'

const TEXT_ENTRY_INPUT_TYPES = new Set([
  'text',
  'number',
  'email',
  'password',
  'search',
  'tel',
  'url',
])

/** True when focus is in a control where letter/number keys are typed (not buttons/checkboxes). */
export function keyboardTargetBlocksShortcut(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  if (tag === 'TEXTAREA') return true
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type.toLowerCase()
    return type === '' || TEXT_ENTRY_INPUT_TYPES.has(type)
  }
  return false
}

export function isModalDialogOpen(): boolean {
  return document.querySelector('[aria-modal="true"]') != null
}

export type UseWindowKeydownOptions = {
  enabled?: boolean
  guard?: () => boolean
}

export function useWindowKeydown(
  handler: (e: KeyboardEvent) => void,
  options?: UseWindowKeydownOptions
): void {
  const enabled = options?.enabled ?? true
  const guard = options?.guard

  useEffect(() => {
    if (!enabled) return

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (keyboardTargetBlocksShortcut(e.target)) return
      if (isModalDialogOpen()) return
      if (guard != null && !guard()) return
      handler(e)
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [enabled, guard, handler])
}
