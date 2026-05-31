import { useCallback, useEffect, useRef } from 'react'
import { useReactFlow, useStoreApi } from '@xyflow/react'
import {
  MAP_ZOOM_KEYBOARD_REPEAT_INTERVAL_MS,
  MAP_ZOOM_KEYBOARD_REPEAT_START_MS,
  MAP_ZOOM_MAX,
  MAP_ZOOM_MIN,
  mapZoomKeyboardStepsPerRepeatTick,
  stepMapZoomBySliderSteps,
} from '../../lib/utils'
import { useWindowKeydown } from '../../lib/keyboardShortcuts'

export function useCenteredViewportZoom(onMapZoomChange: (z: number) => void) {
  const { getViewport, setViewport } = useReactFlow()
  const storeApi = useStoreApi()

  return useCallback(
    (targetZoom: number) => {
      const z = Math.min(MAP_ZOOM_MAX, Math.max(MAP_ZOOM_MIN, Number(targetZoom) || MAP_ZOOM_MIN))
      const apply = () => {
        const domNode = storeApi.getState().domNode
        if (!domNode || domNode.getBoundingClientRect().width <= 0) return false
        const vp = getViewport()
        const rect = domNode.getBoundingClientRect()
        const w = Math.max(rect.width, 1)
        const h = Math.max(rect.height, 1)
        const vz = Math.max(Number(vp.zoom) || MAP_ZOOM_MIN, MAP_ZOOM_MIN)
        const vx = Number.isFinite(vp.x) ? vp.x : 0
        const vy = Number.isFinite(vp.y) ? vp.y : 0
        const cx = (w / 2 - vx) / vz
        const cy = (h / 2 - vy) / vz
        const nx = w / 2 - cx * z
        const ny = h / 2 - cy * z
        if (!Number.isFinite(nx) || !Number.isFinite(ny)) return false
        setViewport({ x: nx, y: ny, zoom: z })
        onMapZoomChange(z)
        return true
      }
      if (apply()) return
      let n = 0
      const tick = () => {
        if (apply()) return
        if (++n >= 30) return
        requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)
    },
    [getViewport, setViewport, storeApi, onMapZoomChange]
  )
}

function isMapZoomInKey(e: KeyboardEvent): boolean {
  return e.key === '+' || e.key === '=' || e.code === 'NumpadAdd'
}

function isMapZoomOutKey(e: KeyboardEvent): boolean {
  return e.key === '-' || e.code === 'NumpadSubtract'
}

function zoomDirectionForKey(e: KeyboardEvent): -1 | 1 | null {
  if (isMapZoomOutKey(e)) return -1
  if (isMapZoomInKey(e)) return 1
  return null
}

type ActiveMapZoomHold = {
  direction: -1 | 1
  pressStartedAt: number
  repeatStartTimeoutId: number
  repeatIntervalId: number | null
}

/** +/- and = zoom in map mode; tap = one step, hold ramps up every 250ms. */
export function MapZoomKeyboardShortcuts({
  onMapZoomChange,
}: {
  onMapZoomChange: (z: number) => void
}) {
  const setZoom = useCenteredViewportZoom(onMapZoomChange)
  const storeApi = useStoreApi()
  const activeHoldRef = useRef<ActiveMapZoomHold | null>(null)

  const applyZoomSteps = useCallback(
    (direction: -1 | 1, deltaSteps: number) => {
      const raw = storeApi.getState().transform?.[2]
      const current = Number.isFinite(raw) && (raw as number) > 0 ? (raw as number) : 1
      setZoom(stepMapZoomBySliderSteps(current, direction * deltaSteps))
    },
    [setZoom, storeApi]
  )

  const stopHold = useCallback(() => {
    const active = activeHoldRef.current
    if (active == null) return
    window.clearTimeout(active.repeatStartTimeoutId)
    if (active.repeatIntervalId != null) {
      window.clearInterval(active.repeatIntervalId)
    }
    activeHoldRef.current = null
  }, [])

  const startHold = useCallback(
    (direction: -1 | 1) => {
      stopHold()
      const pressStartedAt = performance.now()
      applyZoomSteps(direction, 1)

      const repeatStartTimeoutId = window.setTimeout(() => {
        const active = activeHoldRef.current
        if (active == null || active.direction !== direction) return

        const tick = () => {
          const holdMs = performance.now() - pressStartedAt
          applyZoomSteps(direction, mapZoomKeyboardStepsPerRepeatTick(holdMs))
        }

        tick()
        active.repeatIntervalId = window.setInterval(tick, MAP_ZOOM_KEYBOARD_REPEAT_INTERVAL_MS)
      }, MAP_ZOOM_KEYBOARD_REPEAT_START_MS)

      activeHoldRef.current = {
        direction,
        pressStartedAt,
        repeatStartTimeoutId,
        repeatIntervalId: null,
      }
    },
    [applyZoomSteps, stopHold]
  )

  useWindowKeydown(
    useCallback(
      (e: KeyboardEvent) => {
        const direction = zoomDirectionForKey(e)
        if (direction == null) return
        e.preventDefault()
        if (e.repeat) return
        startHold(direction)
      },
      [startHold]
    )
  )

  useEffect(() => {
    const onKeyUp = (e: KeyboardEvent) => {
      if (zoomDirectionForKey(e) == null) return
      stopHold()
    }

    const onBlur = () => stopHold()

    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', onBlur)
    return () => {
      stopHold()
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onBlur)
    }
  }, [stopHold])

  return null
}
