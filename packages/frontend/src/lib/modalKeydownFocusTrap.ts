import { type RefObject, useEffect, useRef } from 'react'

/** Selectors for elements that might participate in the modal Tab cycle (broad, then filtered). */
const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

/**
 * Broad selector candidates include disabled and non-tabbable nodes; the browser skips them on
 * Tab, but this trap builds its own list—so we must match native tab order semantics.
 */
function isTabbableModalElement(el: HTMLElement): boolean {
  if (!el.isConnected) return false
  if (el.tabIndex < 0) return false
  if (el.hasAttribute('hidden')) return false
  if (el.getAttribute('aria-hidden') === 'true') return false
  if (el.getAttribute('aria-disabled') === 'true') return false
  for (let n: HTMLElement | null = el; n; n = n.parentElement) {
    if (n.inert) return false
  }
  try {
    if (el.matches(':disabled')) return false
  } catch {
    return false
  }
  return true
}

function getTabbableElementsInContainer(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    isTabbableModalElement
  )
}

/**
 * When `isOpen`, traps Tab / Shift+Tab within `dialogRef` and calls `onEscape` for Escape
 * (caller should prevent default side effects; Escape is `preventDefault` here).
 */
export function useModalKeydownFocusTrap(
  isOpen: boolean,
  dialogRef: RefObject<HTMLElement | null>,
  onEscape: () => void
): void {
  const onEscapeRef = useRef(onEscape)
  onEscapeRef.current = onEscape
  useEffect(() => {
    if (!isOpen) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onEscapeRef.current()
        return
      }
      if (e.key === 'Tab') {
        const el = dialogRef.current
        if (!el) return
        const focusables = getTabbableElementsInContainer(el)
        const len = focusables.length
        if (len === 0) return
        const i = focusables.indexOf(document.activeElement as HTMLElement)
        if (e.shiftKey) {
          if (i <= 0) {
            e.preventDefault()
            focusables[len - 1]?.focus()
          }
        } else {
          if (i === -1 || i >= len - 1) {
            e.preventDefault()
            focusables[0]?.focus()
          }
        }
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isOpen, dialogRef])
}
