import { describe, expect, it } from 'vitest'
import { keyboardTargetBlocksShortcut } from './keyboardShortcuts'

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
