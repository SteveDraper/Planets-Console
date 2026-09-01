import { beforeEach, describe, expect, it } from 'vitest'
import {
  appendRegisteredMapQueryParams,
  appendRegisteredTableQueryParams,
} from './shellAnalyticQueryParams'
import { useScoresTablePreferencesStore } from '../stores/scoresTablePreferences'
import {
  DEFAULT_CONNECTIONS_MAP_PARAMS,
  useConnectionsMapParamsStore,
} from './connections/connectionsMapParamsStore'

describe('registered analytic query param appenders', () => {
  beforeEach(() => {
    useScoresTablePreferencesStore.setState({
      scoresTableParams: { includeBuildInference: true },
    })
    useConnectionsMapParamsStore.setState({
      connectionsMapParams: DEFAULT_CONNECTIONS_MAP_PARAMS,
    })
  })

  it('appends scores table params from the store without an id switch in the caller', () => {
    const params = new URLSearchParams()
    appendRegisteredTableQueryParams('scores', params)
    expect(params.get('includeBuildInference')).toBe('true')
  })

  it('does not append table params for an unregistered id', () => {
    const params = new URLSearchParams()
    appendRegisteredTableQueryParams('mystery', params)
    expect([...params.keys()]).toEqual([])
  })

  it('appends connections map params from the store', () => {
    const params = new URLSearchParams()
    appendRegisteredMapQueryParams('connections', params)
    expect(params.get('warpSpeed')).toBe('9')
    expect(params.get('flareMode')).toBe('include')
  })
})
