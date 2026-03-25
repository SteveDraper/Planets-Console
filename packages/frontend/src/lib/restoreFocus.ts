export type FocusRestoreCandidate =
  | HTMLElement
  | null
  | undefined
  | (() => HTMLElement | null | undefined)

function resolveCandidate(candidate: FocusRestoreCandidate): HTMLElement | null | undefined {
  if (typeof candidate === 'function') {
    return candidate()
  }
  return candidate ?? undefined
}

function focusBodyAsLastResort(): void {
  if (typeof document === 'undefined') {
    return
  }
  const body = document.body
  if (!body?.isConnected) {
    return
  }
  try {
    if (!body.hasAttribute('tabindex')) {
      body.setAttribute('tabindex', '-1')
    }
    body.focus()
  } catch {
    // ignore
  }
}

/**
 * Returns focus after closing an overlay. Tries each candidate in order (after one frame so
 * unmounts can finish); only focuses when `isConnected` is true. Falls back to `document.body`
 * with `tabindex="-1"` when nothing else works.
 */
export function restoreFocusToElementOrFallback(
  ...candidates: FocusRestoreCandidate[]
): void {
  requestAnimationFrame(() => {
    for (const raw of candidates) {
      const el = resolveCandidate(raw)
      if (el != null && typeof el.focus === 'function' && el.isConnected) {
        el.focus()
        return
      }
    }
    focusBodyAsLastResort()
  })
}
