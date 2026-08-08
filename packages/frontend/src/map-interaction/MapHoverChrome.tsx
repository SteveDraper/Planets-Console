/**
 * Hover chrome for composed **descriptive** hosts and stacked **map-element**
 * contributions on the **map interaction surface**.
 */

import type { ReactNode } from 'react'
import { useStore } from '@xyflow/react'
import type {
  MapHoverBlock,
  MapHoverContribution,
  MapHoverSyncBlock,
} from './mapHoverContributionTypes'
import type {
  ComposedDescriptiveHost,
  MapHoverCompositionResult,
} from './mapHoverCompositionPolicy'
import type { MapPaneClientPos } from './useMapPanePointer'
import { safeZoomScale } from '../lib/mapFlowGeometry'

const LABEL_OFFSET_X_PX = 9
const LABEL_OFFSET_Y_PX = -12

function renderSyncBlocks(blocks: readonly MapHoverSyncBlock[]): ReactNode {
  return blocks.map((block, i) => {
    if (block.type === 'lines') {
      return (
        <div key={`lines-${i}`} className="space-y-0">
          {block.lines.map((line, j) => (
            <div key={`${j}-${line}`}>{line}</div>
          ))}
        </div>
      )
    }
    return <div key={`rich-${i}`}>{block.content}</div>
  })
}

function renderBlocks(blocks: readonly MapHoverBlock[]): ReactNode {
  const sync: MapHoverSyncBlock[] = []
  for (const block of blocks) {
    if (block.type === 'async') {
      if (block.status === 'ready' && block.blocks != null) {
        sync.push(...block.blocks)
      }
      continue
    }
    sync.push(block)
  }
  return renderSyncBlocks(sync)
}

function hostPanePosition(
  host: ComposedDescriptiveHost,
  clientPos: MapPaneClientPos | null,
  domNode: HTMLElement,
  transform: [number, number, number]
): { left: number; top: number; pinned: boolean } | null {
  if (host.placement.mode === 'cursor') {
    if (clientPos == null) return null
    const rect = domNode.getBoundingClientRect()
    return {
      left: clientPos.x - rect.left + 12,
      top: clientPos.y - rect.top - 8,
      pinned: false,
    }
  }
  const [tx, ty, rawScale] = transform
  const scale = safeZoomScale(rawScale)
  // Anchor placement stores flow coordinates directly as flowX/flowY.
  const paneX = host.placement.flowX * scale + tx
  const paneY = host.placement.flowY * scale + ty
  return {
    left: Math.round(paneX + LABEL_OFFSET_X_PX),
    top: Math.round(paneY + LABEL_OFFSET_Y_PX),
    pinned: host.placement.pinned === true,
  }
}

function DescriptiveHostChrome({
  host,
  clientPos,
  domNode,
  transform,
}: {
  host: ComposedDescriptiveHost
  clientPos: MapPaneClientPos | null
  domNode: HTMLElement
  transform: [number, number, number]
}) {
  const pos = hostPanePosition(host, clientPos, domNode, transform)
  if (pos == null || host.sections.length === 0) return null

  const showTitles = host.sections.length > 1
  const cursorHost = host.placement.mode === 'cursor'

  return (
    <div
      className={
        cursorHost
          ? 'pointer-events-none absolute z-[6] max-w-xs font-mono text-xs text-gray-300'
          : pos.pinned
            ? 'pointer-events-auto absolute z-[6] max-w-xs font-mono text-xs text-gray-300'
            : 'pointer-events-none absolute z-[6] max-w-xs font-mono text-xs text-gray-300'
      }
      style={{
        left: pos.left,
        top: pos.top,
        transform: cursorHost ? 'translateY(-100%)' : undefined,
        backgroundColor: '#000000',
        borderRadius: 6,
        padding: cursorHost ? '4px 8px' : undefined,
      }}
      role="tooltip"
      onClick={pos.pinned ? (e) => e.stopPropagation() : undefined}
    >
      {host.sections.map((section, index) => (
        <div
          key={section.contributionId}
          className={index > 0 ? 'mt-1.5 border-t border-gray-700 pt-1.5' : undefined}
        >
          {showTitles ? (
            <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
              {section.title}
            </div>
          ) : null}
          {renderBlocks(section.blocks)}
        </div>
      ))}
    </div>
  )
}

function StackedContributionChrome({
  contribution,
  clientPos,
  domNode,
  transform,
}: {
  contribution: MapHoverContribution
  clientPos: MapPaneClientPos | null
  domNode: HTMLElement
  transform: [number, number, number]
}) {
  // v1: map-element stack uses same placement rules as a single-section host.
  const host: ComposedDescriptiveHost = {
    placement: contribution.placement,
    sections: [
      {
        contributionId: contribution.id,
        role: contribution.role,
        title: contribution.title,
        blocks: contribution.blocks,
      },
    ],
  }
  return (
    <DescriptiveHostChrome
      host={host}
      clientPos={clientPos}
      domNode={domNode}
      transform={transform}
    />
  )
}

type MapHoverChromeProps = {
  composition: MapHoverCompositionResult
  clientPos: MapPaneClientPos | null
}

export function MapHoverChrome({ composition, clientPos }: MapHoverChromeProps) {
  const domNode = useStore((s) => s.domNode ?? null)
  const transform = useStore((s) => s.transform)

  if (domNode == null || !transform) return null

  return (
    <>
      {composition.descriptiveHosts.map((host, i) => (
        <DescriptiveHostChrome
          key={`desc-${i}-${host.sections[0]?.contributionId ?? i}`}
          host={host}
          clientPos={clientPos}
          domNode={domNode}
          transform={transform}
        />
      ))}
      {composition.stacked.map((contribution) => (
        <StackedContributionChrome
          key={contribution.id}
          contribution={contribution}
          clientPos={clientPos}
          domNode={domNode}
          transform={transform}
        />
      ))}
    </>
  )
}
