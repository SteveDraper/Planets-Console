import { act, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { TurnKeyboardShortcuts } from './TurnKeyboardShortcuts'

describe('TurnKeyboardShortcuts', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('steps turn down on i and up on o when enabled', () => {
    const stepTurn = vi.fn()
    render(<TurnKeyboardShortcuts enabled stepTurn={stepTurn} />)

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true })
      )
    })
    expect(stepTurn).toHaveBeenCalledWith(-1)

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'o', bubbles: true, cancelable: true })
      )
    })
    expect(stepTurn).toHaveBeenCalledWith(1)
  })

  it('does not step when disabled', () => {
    const stepTurn = vi.fn()
    render(<TurnKeyboardShortcuts enabled={false} stepTurn={stepTurn} />)

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'i', bubbles: true, cancelable: true })
      )
    })

    expect(stepTurn).not.toHaveBeenCalled()
  })

  it('ignores keys other than i and o', () => {
    const stepTurn = vi.fn()
    render(<TurnKeyboardShortcuts enabled stepTurn={stepTurn} />)

    act(() => {
      window.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'p', bubbles: true, cancelable: true })
      )
    })

    expect(stepTurn).not.toHaveBeenCalled()
  })
})
