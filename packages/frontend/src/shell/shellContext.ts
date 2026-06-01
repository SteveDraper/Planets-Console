import type { AnalyticShellScope } from '../api/bff'
import type { GameInfoShellContext } from '../stores/shell'
import {
  perspectiveOrdinalForName,
  PSEUDO_VIEWPOINT_PERSPECTIVE,
  selectableTurnMaxForShell,
  shouldUsePseudoViewpointForLogin,
  SPECTATOR_VIEWPOINT_NAME,
  viewpointNameForLogin,
  viewpointNameForStoredPerspective,
  type PerspectiveRow,
} from '../lib/gameInfoShell'

export type ShellViewpointRow = {
  name: string
  raceName: string | null
  disabled: boolean
}

export type ShellContextInputs = {
  selectedGameId: string | null
  gameInfoContext: GameInfoShellContext | null
  selectedTurn: number | null
  perspectiveOverrideName: string | null
  loginName: string | null
  storageOnlyLoad: boolean
  storageAvailablePerspectives: number[] | null
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

export function deriveShellDefaultViewpointName(
  gameInfoContext: GameInfoShellContext | null,
  loginName: string | null
): string | null {
  if (!gameInfoContext) return null
  const { perspectives, isGameFinished } = gameInfoContext
  if (shouldUsePseudoViewpointForLogin(perspectives, loginName, isGameFinished)) {
    return SPECTATOR_VIEWPOINT_NAME
  }
  return viewpointNameForLogin(perspectives, loginName)
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
      rows.push({ name: SPECTATOR_VIEWPOINT_NAME, raceName: null, disabled: false })
    }
    rows.push(
      ...perspectives.map((row) => ({
        name: row.name,
        raceName: row.raceName,
        disabled: !storageSlots.has(row.ordinal),
      }))
    )
    return rows
  }
  const finished = inputs.gameInfoContext?.isGameFinished ?? true
  if (finished) {
    return perspectives.map((row) => ({
      name: row.name,
      raceName: row.raceName,
      disabled: false,
    }))
  }
  if (
    shouldUsePseudoViewpointForLogin(
      perspectives,
      inputs.loginName,
      inputs.gameInfoContext?.isGameFinished ?? true
    )
  ) {
    return [
      { name: SPECTATOR_VIEWPOINT_NAME, raceName: null, disabled: false },
      ...perspectives.map((row) => ({
        name: row.name,
        raceName: row.raceName,
        disabled: true,
      })),
    ]
  }
  const allowed = deriveShellDefaultViewpointName(inputs.gameInfoContext, inputs.loginName)
  return perspectives.map((row) => ({
    name: row.name,
    raceName: row.raceName,
    disabled: allowed == null ? true : row.name !== allowed,
  }))
}

export function deriveSelectedViewpointName(inputs: ShellContextInputs): string | null {
  const perspectives = inputs.gameInfoContext?.perspectives ?? []
  const shellPerspectiveNames = perspectives.map((p) => p.name)
  if (shellPerspectiveNames.length === 0) return null

  const loginTrimmed = inputs.loginName?.trim() ?? ''
  if (inputs.storageOnlyLoad && loginTrimmed === '') {
    const stored = inputs.storageAvailablePerspectives ?? []
    const preferred = inputs.perspectiveOverrideName
    if (preferred != null) {
      const preferredOrdinal = perspectiveOrdinalForName(perspectives, preferred)
      if (preferredOrdinal != null && stored.includes(preferredOrdinal)) {
        return preferred
      }
    }
    const firstStored = stored[0]
    if (firstStored != null) {
      return viewpointNameForStoredPerspective(firstStored, perspectives)
    }
    return null
  }

  const finished = inputs.gameInfoContext?.isGameFinished ?? true
  const shellDefaultViewpointName = deriveShellDefaultViewpointName(
    inputs.gameInfoContext,
    inputs.loginName
  )
  if (!finished) {
    if (
      shouldUsePseudoViewpointForLogin(
        perspectives,
        inputs.loginName,
        inputs.gameInfoContext?.isGameFinished ?? true
      )
    ) {
      return SPECTATOR_VIEWPOINT_NAME
    }
    if (shellDefaultViewpointName && shellPerspectiveNames.includes(shellDefaultViewpointName)) {
      return shellDefaultViewpointName
    }
    return shellPerspectiveNames[0] ?? null
  }

  const preferred = inputs.perspectiveOverrideName ?? shellDefaultViewpointName
  if (preferred && shellPerspectiveNames.includes(preferred)) return preferred
  return shellPerspectiveNames[0] ?? null
}

export function deriveAnalyticScope(inputs: ShellContextInputs): AnalyticShellScope | null {
  if (!inputs.selectedGameId || inputs.selectedTurn == null) return null
  const perspectives = inputs.gameInfoContext?.perspectives ?? []
  const selectedViewpointName = deriveSelectedViewpointName(inputs)
  const ordinal = perspectiveOrdinalForName(perspectives, selectedViewpointName)
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
  perspectiveOverrideName: string | null
): boolean {
  if (!gameInfoContext || gameInfoContext.isGameFinished) {
    return false
  }
  const allowed = deriveShellDefaultViewpointName(gameInfoContext, loginName)
  if (perspectiveOverrideName == null || allowed == null) {
    return false
  }
  return perspectiveOverrideName.toLowerCase() !== allowed.toLowerCase()
}

export function isViewpointChangeAllowed(
  name: string,
  gameInfoContext: GameInfoShellContext | null,
  loginName: string | null,
  storageOnlyLoad: boolean,
  storageAvailablePerspectives: number[] | null,
  perspectives: PerspectiveRow[]
): boolean {
  const loginTrimmed = loginName?.trim() ?? ''
  if (storageOnlyLoad && loginTrimmed === '') {
    const ordinal = perspectiveOrdinalForName(perspectives, name)
    return ordinal != null && (storageAvailablePerspectives ?? []).includes(ordinal)
  }
  if (gameInfoContext && !gameInfoContext.isGameFinished) {
    const allowed = deriveShellDefaultViewpointName(gameInfoContext, loginName)
    return allowed != null && name.trim().toLowerCase() === allowed.trim().toLowerCase()
  }
  return true
}
