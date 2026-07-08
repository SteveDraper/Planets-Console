import type { AnalyticShellScope } from '../api/bff'
import type { GameInfoShellContext } from '../stores/shell'
import {
  perspectiveDisplayName,
  PSEUDO_VIEWPOINT_PERSPECTIVE,
  selectableTurnMaxForShell,
  shouldUsePseudoViewpointForLogin,
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
  loginName: string | null
): number | null {
  if (!gameInfoContext) return null
  const { perspectives, isGameFinished } = gameInfoContext
  if (shouldUsePseudoViewpointForLogin(perspectives, loginName, isGameFinished)) {
    return PSEUDO_VIEWPOINT_PERSPECTIVE
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
    const rows: ShellViewpointRow[] = []
    if (storageSlots.has(PSEUDO_VIEWPOINT_PERSPECTIVE)) {
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
        disabled: !storageSlots.has(row.ordinal),
      }))
    )
    return rows
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
  if (
    shouldUsePseudoViewpointForLogin(
      perspectives,
      inputs.loginName,
      isGameFinishedForShell(inputs.gameInfoContext)
    )
  ) {
    return [
      {
        ordinal: PSEUDO_VIEWPOINT_PERSPECTIVE,
        displayName: SPECTATOR_VIEWPOINT_NAME,
        raceName: null,
        disabled: false,
      },
      ...perspectives.map((row) => ({
        ordinal: row.ordinal,
        displayName: shellDisplayName(row, inputs),
        raceName: row.raceName,
        disabled: true,
      })),
    ]
  }
  const allowed = deriveShellDefaultViewpointOrdinal(inputs.gameInfoContext, inputs.loginName)
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

  const finished = isGameFinishedForShell(inputs.gameInfoContext)
  const shellDefaultOrdinal = deriveShellDefaultViewpointOrdinal(
    inputs.gameInfoContext,
    inputs.loginName
  )
  if (!finished) {
    if (
      shouldUsePseudoViewpointForLogin(
        perspectives,
        inputs.loginName,
        isGameFinishedForShell(inputs.gameInfoContext)
      )
    ) {
      return PSEUDO_VIEWPOINT_PERSPECTIVE
    }
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
  return {
    gameId: inputs.selectedGameId,
    turn: dataTurn,
    perspective: ordinal,
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

/** Whether an in-progress override should be cleared after login change. */
export function shouldClearInProgressPerspectiveOverride(
  gameInfoContext: GameInfoShellContext | null,
  loginName: string | null,
  perspectiveOverrideOrdinal: number | null
): boolean {
  if (!gameInfoContext || isGameFinishedForShell(gameInfoContext)) {
    return false
  }
  const allowed = deriveShellDefaultViewpointOrdinal(gameInfoContext, loginName)
  if (perspectiveOverrideOrdinal == null || allowed == null) {
    return false
  }
  return perspectiveOverrideOrdinal !== allowed
}

export function isViewpointChangeAllowed(
  ordinal: number,
  gameInfoContext: GameInfoShellContext | null,
  loginName: string | null,
  storageOnlyLoad: boolean,
  storageAvailablePerspectives: number[] | null
): boolean {
  const loginTrimmed = loginName?.trim() ?? ''
  if (storageOnlyLoad && loginTrimmed === '') {
    return (storageAvailablePerspectives ?? []).includes(ordinal)
  }
  if (gameInfoContext && !isGameFinishedForShell(gameInfoContext)) {
    const allowed = deriveShellDefaultViewpointOrdinal(gameInfoContext, loginName)
    return allowed != null && ordinal === allowed
  }
  return true
}
