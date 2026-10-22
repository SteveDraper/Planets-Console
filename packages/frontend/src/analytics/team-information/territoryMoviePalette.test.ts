import { describe, expect, it } from 'vitest'
import {
  TERRITORY_MOVIE_PALETTE,
  chooseMaximin,
  deltaE00Srgb,
  moviePalette,
  pickMaximinRgb,
  srgbToLab,
  type Rgb,
} from './territoryMoviePalette'

describe('territory movie palette', () => {
  it('bakes indexes 0 through 59 with the published prefix and the amendment', () => {
    expect(TERRITORY_MOVIE_PALETTE).toHaveLength(60)
    expect(TERRITORY_MOVIE_PALETTE[0]).toBe('#8fff00')
    expect(TERRITORY_MOVIE_PALETTE[31]).toBe('#fff48f')
    expect(TERRITORY_MOVIE_PALETTE[32]).toBe('#865d57')
    expect(TERRITORY_MOVIE_PALETTE[59]).toBe('#ab8700')
  })

  it('measures the published distance from index 0 to index 1', () => {
    const white = srgbToLab(255, 255, 255)
    const black = srgbToLab(0, 0, 0)
    expect(white[0]).toBeCloseTo(100, 6)
    expect(white[1]).toBeCloseTo(0, 6)
    expect(white[2]).toBeCloseTo(0, 6)
    expect(black[0]).toBeCloseTo(0, 6)
    const chartreuse = srgbToLab(143, 255, 0)
    expect(chartreuse[0]).toBeCloseTo(90.49, 2)
    expect(deltaE00Srgb([143, 255, 0], [0, 0, 110])).toBeCloseTo(119.474, 3)
    expect(deltaE00Srgb([0, 0, 110], [143, 255, 0])).toBeCloseTo(119.474, 3)
  })

  it('keeps the earlier candidate when minimum distances tie', () => {
    expect(
      chooseMaximin([
        { rgb: [1, 0, 0], minDistance: 5 },
        { rgb: [0, 1, 0], minDistance: 5 },
        { rgb: [0, 0, 1], minDistance: 4 },
      ])
    ).toEqual([1, 0, 0])
    expect(
      chooseMaximin([
        { rgb: [1, 0, 0], minDistance: 5 },
        { rgb: [0, 0, 2], minDistance: 6 },
      ])
    ).toEqual([0, 0, 2])
  })

  it('picks the candidate farthest from the colors already chosen', () => {
    const existing: Rgb[] = [[0, 0, 0]]
    expect(
      pickMaximinRgb(existing, [
        [8, 8, 8],
        [255, 255, 255],
      ])
    ).toEqual([255, 255, 255])
  })

  it('does not recompute indexes 0 through 59 when the legend is longer', async () => {
    const nextColor = async () => [1, 2, 3] as Rgb
    const withinBaked = await moviePalette(11, nextColor)
    expect(withinBaked).toEqual([...TERRITORY_MOVIE_PALETTE])

    let calls = 0
    const extended = await moviePalette(62, async (existing) => {
      calls += 1
      expect(existing.map((rgb) => `#${rgb.map((channel) => channel.toString(16).padStart(2, '0')).join('')}`).slice(0, 60)).toEqual(
        [...TERRITORY_MOVIE_PALETTE]
      )
      return [calls, 0, 0]
    })
    expect(extended.slice(0, 60)).toEqual([...TERRITORY_MOVIE_PALETTE])
    expect(extended[60]).toBe('#010000')
    expect(extended[61]).toBe('#020000')
    expect(calls).toBe(2)
  })
})
