import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PerspectiveRow } from '../../lib/gameInfoShell'
import type { KnownMinefield } from '../../analytics/minefields/wireSchema'
import {
  MapInteractionRegistryProvider,
  useMapInteractionRegistry,
  type MapInteractionHitState,
} from '../mapInteractionRegistry'
import { MinefieldMapInteractionContributor } from './MinefieldMapInteractionContributor'

const HIT: MapInteractionHitState = {
  clientPos: null,
  hitEpoch: 0,
  domNode: null,
  transform: undefined,
}

const field: KnownMinefield = {
  id: 1,
  ownerId: 1,
  isWeb: false,
  isHidden: false,
  x: 100,
  y: 100,
  units: 100,
  infoTurn: 22,
  friendlyCode: '',
  preRadius: 10,
  postRadius: 9,
}

const roster: readonly PerspectiveRow[] = [
  {
    ordinal: 1,
    playerId: 1,
    name: 'Alice',
    raceName: null,
    eliminationTurn: null,
  },
]

function RegistryVersionProbe({ versions }: { versions: number[] }) {
  const { version } = useMapInteractionRegistry()
  versions.push(version)
  return null
}

describe('MinefieldMapInteractionContributor', () => {
  it(
    'registers once and does not exceed max update depth',
    () => {
      const versions: number[] = []
      const minefields = [field]

      render(
        <MapInteractionRegistryProvider hit={HIT}>
          <MinefieldMapInteractionContributor
            minefields={minefields}
            roster={roster}
            shellTurn={22}
            enabled
          />
          <RegistryVersionProbe versions={versions} />
        </MapInteractionRegistryProvider>
      )

      expect(versions.length).toBeLessThan(20)
      expect(versions.at(-1)).toBe(1)
    },
    3000
  )
})
