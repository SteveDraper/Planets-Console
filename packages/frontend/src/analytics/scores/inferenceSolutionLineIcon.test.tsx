import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ScoresInferenceSolutionShipBuild } from '../../api/bff'
import { hullImageUrl } from '../../concepts/hullImageUrl'
import type { MilitaryScoreLineItem } from './inferenceConstraints'
import { InferenceSolutionLineIcon } from './inferenceSolutionLineIcon'

function line(actionId: string, label = actionId): MilitaryScoreLineItem {
  return {
    actionId,
    label,
    count: 1,
    scoreDelta2xPerUnit: 10,
    militaryChangePerUnit: 5,
    scoreDelta2xSubtotal: 10,
    militaryChangeSubtotal: 5,
  }
}

function shipBuild(
  comboId: string,
  hullId: number,
  label = comboId
): ScoresInferenceSolutionShipBuild {
  return { comboId, label, count: 1, hullId }
}

describe('InferenceSolutionLineIcon', () => {
  it('uses hull image from matching shipBuild comboId', () => {
    const { container } = render(
      <InferenceSolutionLineIcon
        line={line('combo_13_9_3_6_8_6', 'Missouri')}
        shipBuilds={[shipBuild('combo_13_9_3_6_8_6', 13, 'Missouri')]}
      />
    )

    expect(container.querySelector('img')).toHaveAttribute(
      'src',
      hullImageUrl(13)
    )
  })

  it('does not use a lone mismatched shipBuild when comboId differs from line actionId', () => {
    const { container } = render(
      <InferenceSolutionLineIcon
        line={line('combo_5_1_2_3_4_5', 'Ruby')}
        shipBuilds={[shipBuild('combo_13_9_3_6_8_6', 13, 'Missouri')]}
      />
    )

    const hullImage = container.querySelector('img')
    expect(hullImage).toHaveAttribute('src', hullImageUrl(5))
    expect(hullImage).not.toHaveAttribute('src', hullImageUrl(13))
  })

  it('parses hull id from combo actionId when no shipBuild matches', () => {
    const { container } = render(
      <InferenceSolutionLineIcon
        line={line('combo_5_1_2_3_4_5', 'Ruby')}
        shipBuilds={[]}
      />
    )

    expect(container.querySelector('img')).toHaveAttribute(
      'src',
      hullImageUrl(5)
    )
  })

  it('falls back to aggregate icon when hull cannot be resolved', () => {
    const { container } = render(
      <InferenceSolutionLineIcon
        line={line('ship_fighters_added_total')}
        shipBuilds={[]}
      />
    )

    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('svg')).not.toBeNull()
  })
})
