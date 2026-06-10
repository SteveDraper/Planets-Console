import { describe, expect, it } from 'vitest'
import { GENERIC_FREIGHTER_HULL_ID, hullImageUrl, normalizeHullPictureId } from './hullImageUrl'

describe('normalizeHullPictureId', () => {
  it('passes through master catalog ids', () => {
    expect(normalizeHullPictureId(13)).toBe(13)
  })

  it('normalizes race-variant hull ids', () => {
    expect(normalizeHullPictureId(1013)).toBe(13)
    expect(normalizeHullPictureId(2013)).toBe(13)
    expect(normalizeHullPictureId(3013)).toBe(13)
  })
})

describe('hullImageUrl', () => {
  it('returns 3D portrait URL by default', () => {
    expect(hullImageUrl(13)).toBe('https://mobile.planets.nu/img/hulls3d/13_p.png')
  })

  it('normalizes race-variant ids in 3D portrait URLs', () => {
    expect(hullImageUrl(1013)).toBe('https://mobile.planets.nu/img/hulls3d/13_p.png')
    expect(hullImageUrl(2013)).toBe('https://mobile.planets.nu/img/hulls3d/13_p.png')
    expect(hullImageUrl(3013)).toBe('https://mobile.planets.nu/img/hulls3d/13_p.png')
  })

  it('returns classic hull art when requested', () => {
    expect(hullImageUrl(13, { classic: true })).toBe(
      'https://mobile.planets.nu/img/hulls/13.png'
    )
    expect(hullImageUrl(13, { classic: true, left: true })).toBe(
      'https://mobile.planets.nu/img/hullsleft/13.png'
    )
  })

  it('returns side-view 3D art when requested', () => {
    expect(hullImageUrl(60, { sideview: true })).toBe(
      'https://mobile.planets.nu/img/hulls3d/60.png'
    )
    expect(hullImageUrl(60, { sideview: true, left: true })).toBe(
      'https://mobile.planets.nu/img/hullsleft3d/60.png'
    )
  })

  it('appends beam suffix for hulls 65 and 71 in classic mode', () => {
    expect(hullImageUrl(71, { classic: true, beams: 6 })).toBe(
      'https://mobile.planets.nu/img/hulls/71-6.png'
    )
    expect(hullImageUrl(65, { classic: true, beams: 4 })).toBe(
      'https://mobile.planets.nu/img/hulls/65-4.png'
    )
  })

  it('documents the generic freighter stand-in hull id', () => {
    expect(GENERIC_FREIGHTER_HULL_ID).toBe(17)
    expect(hullImageUrl(GENERIC_FREIGHTER_HULL_ID)).toBe(
      'https://mobile.planets.nu/img/hulls3d/17_p.png'
    )
  })
})
