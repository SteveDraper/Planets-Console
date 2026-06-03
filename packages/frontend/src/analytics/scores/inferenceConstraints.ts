export type InferenceConstraintsSection = {
  turn?: number
  playerId?: number
  militaryDelta2x?: number
  warshipDelta?: number
  freighterDelta?: number
  requestedPriorityPointDelta?: number
  priorityPointConstraintNote?: string
  appliedEqualities?: string[]
}

export type MilitaryScoreLineItem = {
  actionId: string
  label: string
  count: number
  scoreDelta2xPerUnit: number
  militaryChangePerUnit: number
  scoreDelta2xSubtotal: number
  militaryChangeSubtotal: number
}

export type MilitaryScoreArithmetic = {
  observedMilitaryChange: number
  observedMilitaryDelta2x: number
  explainedMilitaryChange: number
  explainedMilitaryDelta2x: number
  matchesObserved: boolean
  lineItems: MilitaryScoreLineItem[]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value != null && typeof value === 'object' && !Array.isArray(value)
}

export function readInferenceConstraints(
  diagnostics: Record<string, unknown>
): InferenceConstraintsSection | null {
  const constraints = diagnostics.constraints
  if (!isRecord(constraints)) {
    return null
  }
  return {
    turn: typeof constraints.turn === 'number' ? constraints.turn : undefined,
    playerId:
      typeof constraints.playerId === 'number' ? constraints.playerId : undefined,
    militaryDelta2x:
      typeof constraints.militaryDelta2x === 'number'
        ? constraints.militaryDelta2x
        : undefined,
    warshipDelta:
      typeof constraints.warshipDelta === 'number' ? constraints.warshipDelta : undefined,
    freighterDelta:
      typeof constraints.freighterDelta === 'number' ? constraints.freighterDelta : undefined,
    requestedPriorityPointDelta:
      typeof constraints.requestedPriorityPointDelta === 'number'
        ? constraints.requestedPriorityPointDelta
        : undefined,
    priorityPointConstraintNote:
      typeof constraints.priorityPointConstraintNote === 'string'
        ? constraints.priorityPointConstraintNote
        : undefined,
    appliedEqualities: Array.isArray(constraints.appliedEqualities)
      ? constraints.appliedEqualities.filter((item): item is string => typeof item === 'string')
      : undefined,
  }
}

export function readMilitaryScoreArithmetic(value: unknown): MilitaryScoreArithmetic | null {
  if (!isRecord(value)) {
    return null
  }
  const lineItemsRaw = value.lineItems
  if (!Array.isArray(lineItemsRaw)) {
    return null
  }
  const lineItems: MilitaryScoreLineItem[] = []
  for (const item of lineItemsRaw) {
    if (!isRecord(item)) {
      continue
    }
    if (
      typeof item.actionId !== 'string' ||
      typeof item.label !== 'string' ||
      typeof item.count !== 'number' ||
      typeof item.scoreDelta2xPerUnit !== 'number' ||
      typeof item.militaryChangePerUnit !== 'number' ||
      typeof item.scoreDelta2xSubtotal !== 'number' ||
      typeof item.militaryChangeSubtotal !== 'number'
    ) {
      continue
    }
    lineItems.push({
      actionId: item.actionId,
      label: item.label,
      count: item.count,
      scoreDelta2xPerUnit: item.scoreDelta2xPerUnit,
      militaryChangePerUnit: item.militaryChangePerUnit,
      scoreDelta2xSubtotal: item.scoreDelta2xSubtotal,
      militaryChangeSubtotal: item.militaryChangeSubtotal,
    })
  }
  if (
    typeof value.observedMilitaryChange !== 'number' ||
    typeof value.observedMilitaryDelta2x !== 'number' ||
    typeof value.explainedMilitaryChange !== 'number' ||
    typeof value.explainedMilitaryDelta2x !== 'number' ||
    typeof value.matchesObserved !== 'boolean'
  ) {
    return null
  }
  return {
    observedMilitaryChange: value.observedMilitaryChange,
    observedMilitaryDelta2x: value.observedMilitaryDelta2x,
    explainedMilitaryChange: value.explainedMilitaryChange,
    explainedMilitaryDelta2x: value.explainedMilitaryDelta2x,
    matchesObserved: value.matchesObserved,
    lineItems,
  }
}

/** Scoreboard military change from solver 2× scale (matches Core `military_delta_2x // 2`). */
export function militaryChangeFromDelta2x(militaryDelta2x: number): number {
  return Math.floor(militaryDelta2x / 2)
}

export function formatSignedDelta(value: number): string {
  if (value > 0) {
    return `+${value}`
  }
  return String(value)
}
