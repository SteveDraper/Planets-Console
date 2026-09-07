import type { ScoresInferenceRowDetail, ScoresInferenceSolution } from '../../api/bff'
import { militaryChangeFromDelta2x } from './inferenceConstraints'

export const SHIP_FIRST_FAMILY_CHIP_LABEL = {
  mine_overshoot: 'Mine leftover',
  ammo_top_up: 'Ammo top-up',
} as const

/** Mix-list phrase without trailing punctuation; join/period is applied at each call site. */
export const SHIP_FIRST_MIX_PHRASE = 'Mix of mine leftover and ammo top-up'

export type ShipFirstFamilyTag = keyof typeof SHIP_FIRST_FAMILY_CHIP_LABEL

export function shipFirstFamilyChipLabel(family: ShipFirstFamilyTag): string {
  return SHIP_FIRST_FAMILY_CHIP_LABEL[family]
}

export function heldShipFirstFamilies(
  solutions: ScoresInferenceSolution[]
): Set<ShipFirstFamilyTag> {
  const families = new Set<ShipFirstFamilyTag>()
  for (const solution of solutions) {
    if (solution.shipFirstFamily != null) {
      families.add(solution.shipFirstFamily)
    }
  }
  return families
}

export function shipFirstListMixesFamilies(solutions: ScoresInferenceSolution[]): boolean {
  return heldShipFirstFamilies(solutions).size > 1
}

export function isCompleteShipFirstResidualList(detail: ScoresInferenceRowDetail): boolean {
  return (
    detail.displayStatus === 'mine_score_residual' &&
    detail.isComplete &&
    detail.solutionCount > 0
  )
}

export function shipFirstResidualAccessibleLabel(detail: ScoresInferenceRowDetail): string {
  const count = detail.solutionCount
  const countPart = count === 1 ? '1 probable build' : `${count} probable builds`
  const parts = [countPart]
  if (shipFirstListMixesFamilies(detail.solutions)) {
    parts.push(SHIP_FIRST_MIX_PHRASE)
  }
  if (detail.unexplainedMilitaryDelta2x != null) {
    parts.push(`Leftover ${militaryChangeFromDelta2x(detail.unexplainedMilitaryDelta2x)}`)
  }
  return `${parts.join('. ')}.`
}
