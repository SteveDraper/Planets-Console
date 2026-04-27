import { createElement, useRef, type ReactNode, type FunctionComponent } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { useModalKeydownFocusTrap } from './modalKeydownFocusTrap'

const FocusTrapHarness: FunctionComponent<{
  isOpen: boolean
  onEscape: () => void
  children?: ReactNode
}> = function FocusTrapHarness({ isOpen, onEscape, children }) {
  const ref = useRef<HTMLDivElement>(null)
  useModalKeydownFocusTrap(isOpen, ref, onEscape)
  return createElement('div', { ref }, children)
}

function keydownOnDocument(
  key: string,
  options: { shiftKey?: boolean } = {}
): KeyboardEvent {
  const ev = new KeyboardEvent('keydown', {
    key,
    shiftKey: options.shiftKey ?? false,
    bubbles: true,
    cancelable: true,
  })
  document.dispatchEvent(ev)
  return ev
}

describe('useModalKeydownFocusTrap', () => {
  it('calls onEscape and prevents default when Escape is pressed', () => {
    const onEscape = vi.fn()
    render(
      createElement(
        FocusTrapHarness,
        { isOpen: true, onEscape },
        createElement('button', { type: 'button' }, 'one')
      )
    )

    const ev = keydownOnDocument('Escape')
    expect(onEscape).toHaveBeenCalledTimes(1)
    expect(ev.defaultPrevented).toBe(true)
  })

  it('wraps focus forward on Tab from the last tabbable element to the first', () => {
    const onEscape = vi.fn()
    render(
      createElement(
        FocusTrapHarness,
        { isOpen: true, onEscape },
        createElement('button', { type: 'button' }, 'first'),
        createElement('button', { type: 'button' }, 'second')
      )
    )

    const first = screen.getByRole('button', { name: 'first' })
    const second = screen.getByRole('button', { name: 'second' })
    second.focus()
    expect(document.activeElement).toBe(second)

    keydownOnDocument('Tab')
    expect(document.activeElement).toBe(first)
  })

  it('wraps focus backward on Shift+Tab from the first tabbable element to the last', () => {
    const onEscape = vi.fn()
    render(
      createElement(
        FocusTrapHarness,
        { isOpen: true, onEscape },
        createElement('button', { type: 'button' }, 'first'),
        createElement('button', { type: 'button' }, 'second')
      )
    )

    const first = screen.getByRole('button', { name: 'first' })
    const second = screen.getByRole('button', { name: 'second' })
    first.focus()
    expect(document.activeElement).toBe(first)

    keydownOnDocument('Tab', { shiftKey: true })
    expect(document.activeElement).toBe(second)
  })

  it('moves focus to the first tabbable on Tab when focus is not on a tabbable in the container', () => {
    const onEscape = vi.fn()
    render(
      createElement(
        FocusTrapHarness,
        { isOpen: true, onEscape },
        createElement('button', { type: 'button' }, 'only')
      )
    )
    const only = screen.getByRole('button', { name: 'only' })
    const outside = document.createElement('button')
    outside.type = 'button'
    outside.textContent = 'outside'
    document.body.appendChild(outside)
    try {
      outside.focus()
      expect(document.activeElement).toBe(outside)
      keydownOnDocument('Tab')
      expect(document.activeElement).toBe(only)
    } finally {
      outside.remove()
    }
  })

  it('excludes hidden, disabled, aria-hidden, and inert-subtree elements from the tab order', () => {
    const onEscape = vi.fn()
    const { getByTestId } = render(
      createElement(
        FocusTrapHarness,
        { isOpen: true, onEscape },
        createElement('button', { type: 'button' }, 'alpha'),
        createElement('button', { type: 'button' }, 'beta'),
        createElement('button', { type: 'button', hidden: true }, 'hidden'),
        createElement('input', { disabled: true, defaultValue: 'x' }),
        createElement(
          'div',
          { 'data-testid': 'inert-wrap' },
          createElement('button', { type: 'button' }, 'inert child')
        ),
        createElement('button', { type: 'button', 'aria-hidden': true }, 'aria')
      )
    )
    // JSDOM does not set `inert` on elements from the HTML inert attribute; the trap still checks `element.inert`.
    Object.defineProperty(getByTestId('inert-wrap'), 'inert', {
      value: true,
      configurable: true,
    })

    const alpha = screen.getByRole('button', { name: 'alpha' })
    const beta = screen.getByRole('button', { name: 'beta' })

    beta.focus()
    keydownOnDocument('Tab')
    expect(document.activeElement).toBe(alpha)

    alpha.focus()
    keydownOnDocument('Tab', { shiftKey: true })
    expect(document.activeElement).toBe(beta)
  })
})
