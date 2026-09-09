import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { MapInteractionContributor } from './mapInteractionContributorTypes'
import {
  MapInteractionRegistryProvider,
  useMapInteractionRegistry,
  type MapInteractionHitState,
} from './mapInteractionRegistry'
import { useMapInteractionContributor } from './useMapInteractionContributor'

const HIT: MapInteractionHitState = {
  clientPos: null,
  hitEpoch: 0,
  domNode: null,
  transform: undefined,
}

const contributor: MapInteractionContributor = {
  id: 'probe',
  role: 'minefield',
  hitTest: () => null,
}

function RegistryVersionProbe({ versions }: { versions: number[] }) {
  const { version } = useMapInteractionRegistry()
  versions.push(version)
  return null
}

describe('useMapInteractionContributor', () => {
  it(
    'does not loop when revision is an inline deps list of stable values',
    () => {
      const versions: number[] = []
      const minefields = [{ id: 1 }]
      const roster = [{ name: 'alice' }]
      const shellTurn = 22

      function Subscriber() {
        // Same pattern as MinefieldMapInteractionContributor: an inline list that
        // is a new array every render, with stable element identities.
        useMapInteractionContributor(contributor, [minefields, roster, shellTurn])
        return null
      }

      render(
        <MapInteractionRegistryProvider hit={HIT}>
          <Subscriber />
          <RegistryVersionProbe versions={versions} />
        </MapInteractionRegistryProvider>
      )

      expect(versions.length).toBeLessThan(20)
      expect(versions.at(-1)).toBe(1)
    },
    3000
  )

  it('bumps registry version when a revision dep identity changes', () => {
    const versions: number[] = []
    function Subscriber({ fields }: { fields: { id: number }[] }) {
      useMapInteractionContributor(contributor, [fields])
      return null
    }

    const { rerender } = render(
      <MapInteractionRegistryProvider hit={HIT}>
        <Subscriber fields={[{ id: 1 }]} />
        <RegistryVersionProbe versions={versions} />
      </MapInteractionRegistryProvider>
    )

    const afterMount = versions.at(-1)
    expect(afterMount).toBe(1)

    rerender(
      <MapInteractionRegistryProvider hit={HIT}>
        <Subscriber fields={[{ id: 2 }]} />
        <RegistryVersionProbe versions={versions} />
      </MapInteractionRegistryProvider>
    )

    expect(versions.at(-1)).toBeGreaterThan(afterMount!)
  })
})
