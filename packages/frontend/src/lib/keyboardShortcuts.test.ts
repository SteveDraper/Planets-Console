import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import {
  isModalDialogOpen,
  keyboardTargetBlocksShortcut,
  useWindowKeydown,
} from './keyboardShortcuts'

describe('keyboardTargetBlocksShortcut', () => {
  it('blocks text entry inputs and textareas', () => {
    expect(
      keyboardTargetBlocksShortcut(Object.assign(document.createElement('input'), { type: 'text' }))
    ).toBe(true)
    expect(
      keyboardTargetBlocksShortcut(Object.assign(document.createElement('input'), { type: 'number' }))
    ).toBe(true)
    expect(keyboardTargetBlocksShortcut(document.createElement('textarea'))).toBe(true)
    expect(keyboardTargetBlocksShortcut(document.createElement('input'))).toBe(true)
  })

  it('allows checkboxes, buttons, and range sliders', () => {
    expect(
      keyboardTargetBlocksShortcut(
        Object.assign(document.createElement('input'), { type: 'checkbox' })
      )
    ).toBe(false)
    expect(
      keyboardTargetBlocksShortcut(Object.assign(document.createElement('input'), { type: 'range' }))
    ).toBe(false)
    expect(keyboardTargetBlocksShortcut(document.createElement('button'))).toBe(false)
  })

  it('allows select elements', () => {
    expect(keyboardTargetBlocksShortcut(document.createElement('select'))).toBe(false)
  })
})

describe('isModalDialogOpen', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('returns true when an aria-modal element is present', () => {
    const dialog = document.createElement('div')
    dialog.setAttribute('aria-modal', 'true')
    document.body.append(dialog)
    expect(isModalDialogOpen()).toBe(true)
  })

  it('returns false when no modal is present', () => {
    expect(isModalDialogOpen()).toBe(false)
  })
})

describe('useWindowKeydown', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('invokes handler for unmodified keydown when enabled', () => {
    const handler = vi.fn()
    renderHook(() => useWindowKeydown(handler))

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true })
      )
    })

    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler.mock.calls[0][0].key).toBe('i')
  })

  it('does not register a listener when enabled is false', () => {
    const handler = vi.fn()
    renderHook(() => useWindowKeydown(handler, { enabled: false }))

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true })
      )
    })

    expect(handler).not.toHaveBeenCalled()
  })

  it('skips handler when ctrl, meta, or alt is pressed', () => {
    const handler = vi.fn()
    renderHook(() => useWindowKeydown(handler))

    for (const init of [
      { ctrlKey: true },
      { metaKey: true },
      { altKey: true },
    ] satisfies KeyboardEventInit[]) {
      handler.mockClear()
      act(() => {
        window.dispatchEvent(
          new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true, ...init })
        )
      })
      expect(handler).not.toHaveBeenCalled()
    }
  })

  it('skips handler when focus is in a text entry control', () => {
    const handler = vi.fn()
    renderHook(() => useWindowKeydown(handler))

    const input = Object.assign(document.createElement('input'), { type: 'text' })
    document.body.append(input)

    act(() => {
      input.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true })
      )
    })

    expect(handler).not.toHaveBeenCalled()
  })

  it('skips handler when a modal dialog is open', () => {
    const handler = vi.fn()
    renderHook(() => useWindowKeydown(handler))

    const dialog = document.createElement('div')
    dialog.setAttribute('aria-modal', 'true')
    document.body.append(dialog)

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true })
      )
    })

    expect(handler).not.toHaveBeenCalled()
  })

  it('skips handler when custom guard returns false', () => {
    const handler = vi.fn()
    const guard = vi.fn(() => false)
    renderHook(() => useWindowKeydown(handler, { guard }))

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true })
      )
    })

    expect(guard).toHaveBeenCalledTimes(1)
    expect(handler).not.toHaveBeenCalled()
  })

  it('invokes handler when custom guard returns true', () => {
    const handler = vi.fn()
    renderHook(() => useWindowKeydown(handler, { guard: () => true }))

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'o', bubbles: true, cancelable: true })
      )
    })

    expect(handler).toHaveBeenCalledTimes(1)
  })

  it('removes listener on unmount', () => {
    const handler = vi.fn()
    const { unmount } = renderHook(() => useWindowKeydown(handler))

    unmount()

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true })
      )
    })

    expect(handler).not.toHaveBeenCalled()
  })
})
