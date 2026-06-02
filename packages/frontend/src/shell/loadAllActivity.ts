import type { LoadAllProgressUpdate } from '../api/bff'

export type LoadAllActivity =
  | { phase: 'idle' }
  | { phase: 'awaiting-refresh' }
  | { phase: 'streaming'; progress: LoadAllProgressUpdate }

export const idleLoadAllActivity: LoadAllActivity = { phase: 'idle' }

export function isLoadAllActivityPending(activity: LoadAllActivity): boolean {
  return activity.phase !== 'idle'
}

export function loadAllProgressFromActivity(
  activity: LoadAllActivity
): LoadAllProgressUpdate | null {
  return activity.phase === 'streaming' ? activity.progress : null
}

export const initialLoadAllStreamingProgress: LoadAllProgressUpdate = {
  phase: 'download',
  perspective: 0,
  perspective_total: 0,
  turn: 0,
  turn_total: 0,
  message: 'Starting load…',
}

export function streamingLoadAllActivity(
  progress: LoadAllProgressUpdate = initialLoadAllStreamingProgress
): LoadAllActivity {
  return { phase: 'streaming', progress }
}
