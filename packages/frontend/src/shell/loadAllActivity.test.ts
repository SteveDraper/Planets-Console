import { describe, expect, it } from 'vitest'
import {
  idleLoadAllActivity,
  initialLoadAllStreamingProgress,
  isLoadAllActivityPending,
  loadAllProgressFromActivity,
  streamingLoadAllActivity,
} from './loadAllActivity'

describe('loadAllActivity', () => {
  it('treats only idle as not pending', () => {
    expect(isLoadAllActivityPending(idleLoadAllActivity)).toBe(false)
    expect(isLoadAllActivityPending({ phase: 'awaiting-refresh' })).toBe(true)
    expect(isLoadAllActivityPending(streamingLoadAllActivity())).toBe(true)
  })

  it('exposes progress only while streaming', () => {
    expect(loadAllProgressFromActivity(idleLoadAllActivity)).toBeNull()
    expect(loadAllProgressFromActivity({ phase: 'awaiting-refresh' })).toBeNull()
    expect(loadAllProgressFromActivity(streamingLoadAllActivity())).toEqual(
      initialLoadAllStreamingProgress
    )
  })
})
