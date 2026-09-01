import { useScoresTablePreferencesStore } from '../../stores/scoresTablePreferences'
import { appendScoresTableQueryParams } from './api'

/** Append Scores table query params from the persisted preferences store. */
export function appendScoresTableQueryParamsFromStore(params: URLSearchParams): void {
  appendScoresTableQueryParams(
    params,
    useScoresTablePreferencesStore.getState().scoresTableParams
  )
}
