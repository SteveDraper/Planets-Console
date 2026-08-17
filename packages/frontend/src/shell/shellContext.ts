import type { AnalyticShellScope } from '../api/bff'
import type { GameInfoShellContext } from '../stores/shell'
import {
  perspectiveDisplayName,
  PSEUDO_VIEWPOINT_PERSPECTIVE,
  selectableTurnMaxForShell,
  SPECTATOR_VIEWPOINT_NAME,
  viewpointOrdinalForLogin,
  type PerspectiveRow,
} from '../lib/gameInfoShell'

export type ShellViewpointRow = {
  ordinal: number
  displayName: string
  raceName: string | null
  disabled: boolean
}

export type ShellContextInputs = {
  selectedGameId: string | null
  gameInfoContext: GameInfoShellContext | null
  selectedTurn: number | null
  perspectiveOverrideOrdinal: number | null
  loginName: string | null
  storageOnlyLoad: boolean
  storageAvailablePerspectives: number[] | null
  /** Core/BFF allowed slots when login is set; null while loading or when login is empty. */
  eligiblePerspectives: number[] | null
  viewedDataTurn: number | null
  turnUsernamesByPlayerId: ReadonlyMap<number, string> | null
}

export function deriveShellTurnMax(
  gameInfoContext: GameInfoShellContext | null
): number | null {
  if (!gameInfoContext) return null
  return selectableTurnMaxForShell(gameInfoContext.turn)
}

export type TurnView = {
  selectedTurn: number | null
  dataTurn: number | null
  futureOffset: number
  isFuture: boolean
}

/** Selected turn may exceed shellTurnMax (future "time machine" turns); fetches use dataTurn only. */
export function deriveTurnView(
  selectedTurn: number | null,
  shellTurnMax: number | null
): TurnView {
  if (selectedTurn == null) {
    return {
      selectedTurn: null,
      dataTurn: null,
      futureOffset: 0,
      isFuture: false,
    }
  }
  if (shellTurnMax == null) {
    return {
      selectedTurn,
      dataTurn: selectedTurn,
      futureOffset: 0,
      isFuture: false,
    }
  }
  const futureOffset = Math.max(0, selectedTurn - shellTurnMax)
  return {
    selectedTurn,
    dataTurn: Math.min(selectedTurn, shellTurnMax),
    futureOffset,
    isFuture: futureOffset > 0,
  }
}

export function isGameFinishedForShell(gameInfoContext: GameInfoShellContext | null): boolean {
  return gameInfoContext?.isGameFinished ?? true
}

export function deriveShellDefaultViewpointOrdinal(
  gameInfoContext: GameInfoShellContext | null,
  loginName: string | null,
  eligiblePerspectives: number[] | null
): number | null {
  if (!gameInfoContext) return null
  const { perspectives } = gameInfoContext
  if (eligiblePerspectives != null) {
    const allowed = new Set(eligiblePerspectives)
    if (allowed.has(PSEUDO_VIEWPOINT_PERSPECTIVE)) {
      return PSEUDO_VIEWPOINT_PERSPECTIVE
    }
    const loginSlot = viewpointOrdinalForLogin(perspectives, loginName)
    if (loginSlot != null && allowed.has(loginSlot)) {
      return loginSlot
    }
    const playerSlots = [...allowed]
      .filter((slot) => slot !== PSEUDO_VIEWPOINT_PERSPECTIVE)
      .sort((a, b) => a - b)
    return playerSlots[0] ?? null
  }
  return viewpointOrdinalForLogin(perspectives, loginName)
}

function shellDisplayName(
  row: PerspectiveRow,
  inputs: ShellContextInputs
): string {
  return perspectiveDisplayName(
    row,
    inputs.viewedDataTurn,
    inputs.turnUsernamesByPlayerId
  )
}

function viewpointsFromEligibleSet(
  perspectives: PerspectiveRow[],
  inputs: ShellContextInputs,
  eligiblePerspectives: number[]
): ShellViewpointRow[] {
  const allowed = new Set(eligiblePerspectives)
  const rows: ShellViewpointRow[] = []
  if (allowed.has(PSEUDO_VIEWPOINT_PERSPECTIVE)) {
    rows.push({
      ordinal: PSEUDO_VIEWPOINT_PERSPECTIVE,
      displayName: SPECTATOR_VIEWPOINT_NAME,
      raceName: null,
      disabled: false,
    })
  }
  rows.push(
    ...perspectives.map((row) => ({
      ordinal: row.ordinal,
      displayName: shellDisplayName(row, inputs),
      raceName: row.raceName,
      disabled: !allowed.has(row.ordinal),
    }))
  )
  return rows
}

export function deriveShellViewpoints(inputs: ShellContextInputs): ShellViewpointRow[] {
  const perspectives = inputs.gameInfoContext?.perspectives ?? []
  if (perspectives.length === 0) {
    return []
  }
  const loginTrimmed = inputs.loginName?.trim() ?? ''
  const storageSlots =
    inputs.storageOnlyLoad && loginTrimmed === ''
      ? new Set(inputs.storageAvailablePerspectives ?? [])
      : null
  if (storageSlots != null) {
    return viewpointsFromEligibleSet(perspectives, inputs, [...storageSlots])
  }
  if (inputs.eligiblePerspectives != null) {
    return viewpointsFromEligibleSet(perspectives, inputs, inputs.eligiblePerspectives)
  }
  if (loginTrimmed !== '') {
    return perspectives.map((row) => ({
      ordinal: row.ordinal,
      displayName: shellDisplayName(row, inputs),
      raceName: row.raceName,
      disabled: true,
    }))
  }
  const finished = isGameFinishedForShell(inputs.gameInfoContext)
  if (finished) {
    return perspectives.map((row) => ({
      ordinal: row.ordinal,
      displayName: shellDisplayName(row, inputs),
      raceName: row.raceName,
      disabled: false,
    }))
  }
  const allowed = deriveShellDefaultViewpointOrdinal(
    inputs.gameInfoContext,
    inputs.loginName,
    null
  )
  return perspectives.map((row) => ({
    ordinal: row.ordinal,
    displayName: shellDisplayName(row, inputs),
    raceName: row.raceName,
    disabled: allowed == null ? true : row.ordinal !== allowed,
  }))
}

export function deriveSelectedViewpointOrdinal(inputs: ShellContextInputs): number | null {
  const perspectives = inputs.gameInfoContext?.perspectives ?? []
  if (perspectives.length === 0) return null

  const loginTrimmed = inputs.loginName?.trim() ?? ''
  if (inputs.storageOnlyLoad && loginTrimmed === '') {
    const stored = inputs.storageAvailablePerspectives ?? []
    const preferred = inputs.perspectiveOverrideOrdinal
    if (preferred != null && stored.includes(preferred)) {
      return preferred
    }
    return stored[0] ?? null
  }

  if (loginTrimmed !== '' && inputs.eligiblePerspectives == null) {
    return null
  }

  const shellDefaultOrdinal = deriveShellDefaultViewpointOrdinal(
    inputs.gameInfoContext,
    inputs.loginName,
    inputs.eligiblePerspectives
  )
  if (inputs.eligiblePerspectives != null) {
    const allowed = new Set(inputs.eligiblePerspectives)
    const preferred = inputs.perspectiveOverrideOrdinal
    if (preferred != null && allowed.has(preferred)) {
      return preferred
    }
    return shellDefaultOrdinal
  }

  const finished = isGameFinishedForShell(inputs.gameInfoContext)
  if (!finished) {
    if (
      shellDefaultOrdinal != null &&
      perspectives.some((p) => p.ordinal === shellDefaultOrdinal)
    ) {
      return shellDefaultOrdinal
    }
    return perspectives[0]?.ordinal ?? null
  }

  const preferred = inputs.perspectiveOverrideOrdinal ?? shellDefaultOrdinal
  if (preferred != null && perspectives.some((p) => p.ordinal === preferred)) {
    return preferred
  }
  return perspectives[0]?.ordinal ?? null
}

export function deriveAnalyticScope(inputs: ShellContextInputs): AnalyticShellScope | null {
  if (!inputs.selectedGameId || inputs.selectedTurn == null) return null
  const ordinal = deriveSelectedViewpointOrdinal(inputs)
  if (ordinal == null) return null
  const { dataTurn } = deriveTurnView(
    inputs.selectedTurn,
    deriveShellTurnMax(inputs.gameInfoContext)
  )
  if (dataTurn == null) return null
  const username = inputs.loginName?.trim() ?? ''
  return {
    gameId: inputs.selectedGameId,
    turn: dataTurn,
    perspective: ordinal,
    ...(username ? { username } : {}),
  }
}

export function deriveTurnEnsureEnabled(
  analyticScope: AnalyticShellScope | null,
  loginName: string | null,
  storageOnlyLoad: boolean
): boolean {
  const loginTrimmed = loginName?.trim() ?? ''
  return analyticScope != null && (loginTrimmed !== '' || storageOnlyLoad)
}

export function deriveTurnBlockedNoLogin(
  analyticScope: AnalyticShellScope | null,
  loginName: string | null,
  storageOnlyLoad: boolean
): boolean {
  const loginTrimmed = loginName?.trim() ?? ''
  return analyticScope != null && loginTrimmed === '' && !storageOnlyLoad
}

export function deriveTurnDataReady(turnEnsureEnabled: boolean, turnEnsureSuccess: boolean): boolean {
  return turnEnsureEnabled && turnEnsureSuccess
}

/** Whether an override is outside the BFF-eligible set and should be cleared. */
export function shouldClearInProgressPerspectiveOverride(
  eligiblePerspectives: number[] | null,
  perspectiveOverrideOrdinal: number | null
): boolean {
  if (eligiblePerspectives == null || perspectiveOverrideOrdinal == null) {
    return false
  }
  return !eligiblePerspectives.includes(perspectiveOverrideOrdinal)
}

export function isViewpointChangeAllowed(
  ordinal: number,
  gameInfoContext: GameInfoShellContext | null,
  loginName: string | null,
  storageOnlyLoad: boolean,
  storageAvailablePerspectives: number[] | null,
  eligiblePerspectives: number[] | null
): boolean {
  const loginTrimmed = loginName?.trim() ?? ''
  if (storageOnlyLoad && loginTrimmed === '') {
    return (storageAvailablePerspectives ?? []).includes(ordinal)
  }
  if (eligiblePerspectives != null) {
    return eligiblePerspectives.includes(ordinal)
  }
  if (loginTrimmed !== '') {
    return false
  }
  if (gameInfoContext && !isGameFinishedForShell(gameInfoContext)) {
    const allowed = deriveShellDefaultViewpointOrdinal(gameInfoContext, loginName, null)
    return allowed != null && ordinal === allowed
  }
  return true
}
