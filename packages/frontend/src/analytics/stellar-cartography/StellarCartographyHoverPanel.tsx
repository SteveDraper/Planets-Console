import { useEffect, useRef, useState } from 'react'
import { useStore } from '@xyflow/react'
import {
  isStellarCartographySampleLayerId,
  type StellarCartographySampleEntry,
} from '../../api/bff'
import { fetchStellarCartographySample } from '../../api/bff'
import type { StellarCartographyMapContext, StellarCartographyMapUiConfig } from '../mapLayers'
import { isCartographyLayerShown } from './layers'
import { areCartographyWormholesShown } from './overlayDisplayFilter'
import { flowToMapCellIndices } from '../../lib/planetSpatialGrid'
import { formatStellarCartographySampleLine } from './sampleTooltipFormat'

const SAMPLE_DEBOUNCE_MS = 100

type StellarCartographyHoverPanelProps = {
  cartography: StellarCartographyMapContext
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

function filterSampleEntries(
  entries: StellarCartographySampleEntry[],
  config: StellarCartographyMapUiConfig
): StellarCartographySampleEntry[] {
  return entries.filter(
    (entry): entry is StellarCartographySampleEntry =>
      isStellarCartographySampleLayerId(entry.layer) &&
      isCartographyLayerShown(entry.layer, config)
  )
}

/** Build stacked hover lines for all active cartography features at a map cell. */
export function buildStellarCartographyHoverLines(
  entries: StellarCartographySampleEntry[],
  wormholeHoverLines: string[] | null,
  config: StellarCartographyMapUiConfig
): string[] {
  const lines = filterSampleEntries(entries, config).map(formatStellarCartographySampleLine)
  if (
    wormholeHoverLines != null &&
    wormholeHoverLines.length > 0 &&
    areCartographyWormholesShown(config)
  ) {
    lines.push(...wormholeHoverLines)
  }
  return lines
}

/** Debounced stacked tooltip for Stellar Cartography map hover sampling (Phase 4b). */
export function StellarCartographyHoverPanel({
  cartography,
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
    if (clientPos == null || !transform) {
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
      void fetchStellarCartographySample(cartography.analyticScope, mapX, mapY)
        .then((data) => {
          if (seq !== requestSeqRef.current) return
          setEntries(filterSampleEntries(data.entries, cartography.config))
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
    cartography,
    clientPos,
    clientToFlowPosition,
    domNode,
    blockedByPlanetHover,
    transform,
  ])

  const lines = buildStellarCartographyHoverLines(
    entries,
    wormholeHoverLines,
    cartography.config
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
