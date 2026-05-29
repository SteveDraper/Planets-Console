import { useEffect, useRef, useState } from 'react'
import { useStore } from '@xyflow/react'
import type { AnalyticShellScope, StellarCartographySampleEntry } from '../../api/bff'
import { fetchStellarCartographySample } from '../../api/bff'
import {
  isCartographyLayerGateEnabled,
  type CartographyLayerId,
  type CartographyLayerVisibility,
  type StellarCartographySettingsGates,
} from './layers'
import {
  isWormholeCartographyActive,
  type WormholeDisplayMode,
} from './wormholeDisplayMode'
import { flowToMapCellIndices } from '../../lib/planetSpatialGrid'
import { formatStellarCartographySampleLine } from './sampleTooltipFormat'

const SAMPLE_DEBOUNCE_MS = 100

type StellarCartographyHoverPanelProps = {
  analyticScope: AnalyticShellScope | null
  sampleEnabled: boolean
  layerVisibility: CartographyLayerVisibility
  settingsGates: StellarCartographySettingsGates
  wormholeDisplayMode: WormholeDisplayMode
  wormholeHoverLines: string[] | null
  /** When a planet hover/pin label is showing, suppress cartography hover entirely. */
  blockedByPlanetHover?: boolean
  clientToFlowPosition: (
    clientX: number,
    clientY: number,
    domNode: HTMLElement | null,
    transform: [number, number, number] | undefined,
    paneRect?: Pick<DOMRect, 'left' | 'top'>
  ) => { x: number; y: number } | null
}

function isLayerActive(
  layerId: CartographyLayerId,
  layerVisibility: CartographyLayerVisibility,
  settingsGates: StellarCartographySettingsGates,
  wormholeDisplayMode: WormholeDisplayMode
): boolean {
  if (layerId === 'wormholes') {
    return (
      isCartographyLayerGateEnabled(settingsGates, 'wormholes') &&
      isWormholeCartographyActive(wormholeDisplayMode)
    )
  }
  return (
    isCartographyLayerGateEnabled(settingsGates, layerId) &&
    (layerVisibility[layerId] ?? true)
  )
}

function filterSampleEntries(
  entries: StellarCartographySampleEntry[],
  layerVisibility: CartographyLayerVisibility,
  settingsGates: StellarCartographySettingsGates,
  wormholeDisplayMode: WormholeDisplayMode
): StellarCartographySampleEntry[] {
  return entries.filter((entry) =>
    isLayerActive(entry.layer as CartographyLayerId, layerVisibility, settingsGates, wormholeDisplayMode)
  )
}

/** Build stacked hover lines for all active cartography features at a map cell. */
export function buildStellarCartographyHoverLines(
  entries: StellarCartographySampleEntry[],
  wormholeHoverLines: string[] | null,
  layerVisibility: CartographyLayerVisibility,
  settingsGates: StellarCartographySettingsGates,
  wormholeDisplayMode: WormholeDisplayMode
): string[] {
  const lines = filterSampleEntries(
    entries,
    layerVisibility,
    settingsGates,
    wormholeDisplayMode
  ).map(formatStellarCartographySampleLine)
  if (
    wormholeHoverLines != null &&
    wormholeHoverLines.length > 0 &&
    isLayerActive('wormholes', layerVisibility, settingsGates, wormholeDisplayMode)
  ) {
    lines.push(...wormholeHoverLines)
  }
  return lines
}

/** Debounced stacked tooltip for Stellar Cartography map hover sampling (Phase 4b). */
export function StellarCartographyHoverPanel({
  analyticScope,
  sampleEnabled,
  layerVisibility,
  settingsGates,
  wormholeDisplayMode,
  wormholeHoverLines,
  blockedByPlanetHover = false,
  clientToFlowPosition,
}: StellarCartographyHoverPanelProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)
  const [clientPos, setClientPos] = useState<{ x: number; y: number } | null>(null)
  const [entries, setEntries] = useState<StellarCartographySampleEntry[]>([])
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const requestSeqRef = useRef(0)

  useEffect(() => {
    const el = domNode
    if (!el) {
      setClientPos(null)
      setEntries([])
      return
    }
    const onMove = (e: MouseEvent) => setClientPos({ x: e.clientX, y: e.clientY })
    const onLeave = () => {
      setClientPos(null)
      setEntries([])
    }
    el.addEventListener('mousemove', onMove)
    el.addEventListener('mouseleave', onLeave)
    return () => {
      el.removeEventListener('mousemove', onMove)
      el.removeEventListener('mouseleave', onLeave)
    }
  }, [domNode])

  useEffect(() => {
    if (debounceRef.current != null) {
      clearTimeout(debounceRef.current)
      debounceRef.current = null
    }
    if (!sampleEnabled || analyticScope == null || clientPos == null || !transform) {
      setEntries([])
      return
    }
    if (blockedByPlanetHover) {
      setEntries([])
      return
    }
    const flow = clientToFlowPosition(clientPos.x, clientPos.y, domNode, transform)
    if (flow == null) {
      setEntries([])
      return
    }
    const { mapX, mapY } = flowToMapCellIndices(flow.x, flow.y)
    const seq = ++requestSeqRef.current
    debounceRef.current = setTimeout(() => {
      debounceRef.current = null
      void fetchStellarCartographySample(analyticScope, mapX, mapY)
        .then((data) => {
          if (seq !== requestSeqRef.current) return
          setEntries(
            filterSampleEntries(data.entries, layerVisibility, settingsGates, wormholeDisplayMode)
          )
        })
        .catch(() => {
          if (seq !== requestSeqRef.current) return
          setEntries([])
        })
    }, SAMPLE_DEBOUNCE_MS)
    return () => {
      if (debounceRef.current != null) {
        clearTimeout(debounceRef.current)
        debounceRef.current = null
      }
    }
  }, [
    analyticScope,
    clientPos,
    clientToFlowPosition,
    domNode,
    layerVisibility,
    sampleEnabled,
    settingsGates,
    wormholeDisplayMode,
    blockedByPlanetHover,
    transform,
  ])

  const lines = buildStellarCartographyHoverLines(
    entries,
    wormholeHoverLines,
    layerVisibility,
    settingsGates,
    wormholeDisplayMode
  )
  if (
    blockedByPlanetHover ||
    lines.length === 0 ||
    clientPos == null ||
    domNode == null
  ) {
    return null
  }

  const rect = domNode.getBoundingClientRect()
  const paneX = clientPos.x - rect.left + 12
  const paneY = clientPos.y - rect.top - 8

  return (
    <div
      className="pointer-events-none absolute z-[6] max-w-xs font-mono text-xs text-gray-300"
      style={{
        left: paneX,
        top: paneY,
        transform: 'translateY(-100%)',
        backgroundColor: '#000000',
        borderRadius: 6,
        padding: '4px 8px',
      }}
    >
      {lines.map((line, i) => (
        <div key={`${i}-${line}`}>{line}</div>
      ))}
    </div>
  )
}
