import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { hullImageUrl } from '../concepts/hullImageUrl'
import { HullIcon } from './HullIcon'

describe('HullIcon', () => {
  it('resolves the image URL through hullImageUrl', () => {
    const { container } = render(<HullIcon hullId={13} className="h-7 w-7" />)
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(img?.getAttribute('src')).toBe(hullImageUrl(13))
    expect(img?.getAttribute('alt')).toBe('')
    expect(img?.className).toContain('h-7')
    expect(img?.className).toContain('object-contain')
  })
})
