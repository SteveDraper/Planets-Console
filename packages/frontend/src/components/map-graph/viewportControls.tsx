import { useCallback, useEffect, useRef, useState } from 'react'
import { useReactFlow, useStore, useStoreApi } from '@xyflow/react'
import type { CombinedMapData } from '../../api/bff'
import {
  MAP_ZOOM_KEYBOARD_REPEAT_INTERVAL_MS,
  MAP_ZOOM_KEYBOARD_REPEAT_START_MS,
  mapZoomKeyboardStepsPerRepeatTick,
  stepMapZoomBySliderSteps,
} from '../../lib/utils'
import {
  CELL_CENTER_OFFSET,
  gameMapYToFlowCenterY,
} from './geometry'

function keyboardTargetBlocksMapZoom(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  return target.isContentEditable
}

function isMapZoomInKey(e: KeyboardEvent): boolean {
  return e.key === '+' || e.key === '=' || e.code === 'NumpadAdd'
}

function isMapZoomOutKey(e: KeyboardEvent): boolean {
  return e.key === '-' || e.code === 'NumpadSubtract'
}

function useCenteredViewportZoom(onMapZoomChange: (z: number) => void) {
  const { getViewport, setViewport } = useReactFlow()
  const storeApi = useStoreApi()

  return useCallback(
    (targetZoom: number) => {
      const z = Math.min(40, Math.max(0.2, Number(targetZoom) || 0.2))
      const apply = () => {
        const domNode = storeApi.getState().domNode
        if (!domNode || domNode.getBoundingClientRect().width <= 0) return false
        const vp = getViewport()
        const rect = domNode.getBoundingClientRect()
        const w = Math.max(rect.width, 1)
        const h = Math.max(rect.height, 1)
        const vz = Math.max(Number(vp.zoom) || 0.2, 0.2)
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

/** Fraction of display area to leave as blank margin on each side when fitting initial view (0.1 = 10%). */
const INITIAL_FIT_MARGIN = 0.1

/**
 * Computes initial viewport so the bounding rectangle of all node centers is
 * centered with a 10% margin (whichever dimension is most constrained).
 * Runs once when the pane has size and nodes are present. Calls onInitialFitDone when done (or when no fit will run).
 */
export function InitialViewportFit({
  nodes,
  onInitialFitDone,
  onMapZoomChange,
}: {
  nodes: CombinedMapData['nodes']
  onInitialFitDone: () => void
  onMapZoomChange: (zoom: number) => void
}) {
  const { setViewport } = useReactFlow()
  const domNode = useStore((s) => s.domNode ?? null)
  const [size, setSize] = useState({ width: 0, height: 0 })
  const hasFittedRef = useRef(false)
  const doneCalledRef = useRef(false)

  const callDoneOnce = useCallback(() => {
    if (doneCalledRef.current) return
    doneCalledRef.current = true
    onInitialFitDone()
  }, [onInitialFitDone])

  useEffect(() => {
    if (!domNode) return
    let raf = 0
    const ro = new ResizeObserver((entries) => {
      const { width, height } = entries[0]?.contentRect ?? { width: 0, height: 0 }
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setSize({ width, height }))
    })
    ro.observe(domNode)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [domNode])

  useEffect(() => {
    if (nodes.length === 0) {
      callDoneOnce()
      return
    }
    if (size.width <= 0 || size.height <= 0 || hasFittedRef.current) return
    const xs = nodes.map((n) => Number(n.x)).filter(Number.isFinite)
    const ys = nodes.map((n) => Number(n.y)).filter(Number.isFinite)
    if (xs.length === 0 || ys.length === 0) {
      callDoneOnce()
      return
    }
    const minFx = Math.min(...xs) + CELL_CENTER_OFFSET
    const maxFx = Math.max(...xs) + CELL_CENTER_OFFSET
    const flowCentersY = ys.map((py) => gameMapYToFlowCenterY(py))
    const minFy = Math.min(...flowCentersY)
    const maxFy = Math.max(...flowCentersY)
    const contentWidth = Math.max(maxFx - minFx, 1)
    const contentHeight = Math.max(maxFy - minFy, 1)
    const centerX = (minFx + maxFx) / 2
    const centerY = (minFy + maxFy) / 2
    const usableW = size.width * (1 - 2 * INITIAL_FIT_MARGIN)
    const usableH = size.height * (1 - 2 * INITIAL_FIT_MARGIN)
    const scaleW = usableW / contentWidth
    const scaleH = usableH / contentHeight
    const zoom = Math.min(40, Math.max(0.2, Math.min(scaleW, scaleH)))
    const x = size.width / 2 - centerX * zoom
    const y = size.height / 2 - centerY * zoom
    hasFittedRef.current = true
    setViewport({ x, y, zoom })
    onMapZoomChange(zoom)
    callDoneOnce()
  }, [nodes, size, setViewport, callDoneOnce, onMapZoomChange])

  return null
}

/** Mirrors React Flow zoom to the app (wheel, pinch, initial fit, slider). */
export function ViewportZoomSync({ onMapZoomChange }: { onMapZoomChange: (z: number) => void }) {
  const raw = useStore((s) => s.transform?.[2])
  const zoom = Number.isFinite(raw) && (raw as number) > 0 ? (raw as number) : 1
  const prev = useRef(zoom)
  const rafRef = useRef<number | null>(null)
  const pendingZoomRef = useRef<number>(zoom)
  useEffect(() => {
    if (Math.abs(prev.current - zoom) < 1e-9) return
    prev.current = zoom
    pendingZoomRef.current = zoom
    if (rafRef.current != null) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = null
      onMapZoomChange(pendingZoomRef.current)
    })
  }, [zoom, onMapZoomChange])
  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current)
    }
  }, [])
  return null
}

/**
 * Registers setZoom(z) so the header slider can set viewport zoom while keeping the view center fixed.
 */
export function SliderZoomControl({
  onMapZoomChange,
  onSetZoomReady,
}: {
  onMapZoomChange: (z: number) => void
  onSetZoomReady: (setZoom: (z: number) => void) => void
}) {
  const setZoom = useCenteredViewportZoom(onMapZoomChange)
  useEffect(() => {
    onSetZoomReady(setZoom)
  }, [onSetZoomReady, setZoom])
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

  useEffect(() => {
    const applyZoomSteps = (direction: -1 | 1, deltaSteps: number) => {
      const raw = storeApi.getState().transform?.[2]
      const current =
        Number.isFinite(raw) && (raw as number) > 0 ? (raw as number) : 1
      setZoom(stepMapZoomBySliderSteps(current, direction * deltaSteps))
    }

    const stopHold = () => {
      const active = activeHoldRef.current
      if (active == null) return
      window.clearTimeout(active.repeatStartTimeoutId)
      if (active.repeatIntervalId != null) {
        window.clearInterval(active.repeatIntervalId)
      }
      activeHoldRef.current = null
    }

    const startHold = (direction: -1 | 1) => {
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
        active.repeatIntervalId = window.setInterval(
          tick,
          MAP_ZOOM_KEYBOARD_REPEAT_INTERVAL_MS
        )
      }, MAP_ZOOM_KEYBOARD_REPEAT_START_MS)

      activeHoldRef.current = {
        direction,
        pressStartedAt,
        repeatStartTimeoutId,
        repeatIntervalId: null,
      }
    }

    const zoomDirectionForKey = (e: KeyboardEvent): -1 | 1 | null => {
      if (isMapZoomOutKey(e)) return -1
      if (isMapZoomInKey(e)) return 1
      return null
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const direction = zoomDirectionForKey(e)
      if (direction == null) return
      if (keyboardTargetBlocksMapZoom(e.target)) return
      if (document.querySelector('[aria-modal="true"]')) return
      e.preventDefault()
      if (e.repeat) return
      startHold(direction)
    }

    const onKeyUp = (e: KeyboardEvent) => {
      if (zoomDirectionForKey(e) == null) return
      stopHold()
    }

    const onBlur = () => stopHold()

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('blur', onBlur)
    return () => {
      stopHold()
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('blur', onBlur)
    }
  }, [setZoom, storeApi])

  return null
}
