import { describe, it, expect, vi } from 'vitest'
import { restoreFocusToElementOrFallback } from './restoreFocus'

function flushAnimationFrame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve())
  })
}

describe('restoreFocusToElementOrFallback', () => {
  it('skips detached elements and focuses a connected fallback', async () => {
    const detached = document.createElement('button')
    const live = document.createElement('button')
    document.body.append(live)
    const focusSpy = vi.spyOn(live, 'focus')

    restoreFocusToElementOrFallback(detached, live)
    await flushAnimationFrame()

    expect(focusSpy).toHaveBeenCalledTimes(1)
    live.remove()
  })

  it('resolves function candidates on each attempt', async () => {
    const live = document.createElement('button')
    document.body.append(live)
    const focusSpy = vi.spyOn(live, 'focus')

    restoreFocusToElementOrFallback(() => null, () => live)
    await flushAnimationFrame()

    expect(focusSpy).toHaveBeenCalledTimes(1)
    live.remove()
  })
})
