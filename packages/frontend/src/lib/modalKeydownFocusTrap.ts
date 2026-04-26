import { type RefObject, useEffect, useRef } from 'react'

/** Selectors for elements that participate in the modal Tab cycle (matches existing modals). */
const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'

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
        const focusables = Array.from(
          el.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
        )
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
