import { describe, expect, it } from 'vitest'
import {
  ionStormCloudPaneShapeToRasterField,
  nebulaCloudPaneShapeToRasterField,
} from './cartographyRasterFieldOverlay'
import type { IonStormCloudPaneShape } from './ionStormCloudOverlay'
import type { NebulaCloudPaneShape } from './nebulaCloudOverlay'

describe('cartographyRasterFieldOverlay', () => {
  it('maps nebula pane shapes to clip and outer stroke paths', () => {
    const shape: NebulaCloudPaneShape = {
      key: 'neb-cloud-Zoie',
      left: 10,
      top: 20,
      width: 100,
      height: 80,
      imageDataUrl: 'data:image/png;base64,abc',
      boundaryPath: 'M 0 0 L 1 1 Z',
      fillClipPathId: 'neb-cloud-Zoie-fill-clip',
      stroke: '#88f',
      strokeWidth: 0.25,
    }

    const mapped = nebulaCloudPaneShapeToRasterField(shape)
    expect(mapped.clipPaths).toEqual(['M 0 0 L 1 1 Z'])
    expect(mapped.strokePaths).toHaveLength(1)
    expect(mapped.strokePaths[0]).toMatchObject({
      pathKey: 'outer',
      path: 'M 0 0 L 1 1 Z',
      stroke: '#88f',
      strokeWidth: 0.25,
    })
  })

  it('maps ion storm pane shapes with class rings before outer edge', () => {
    const shape: IonStormCloudPaneShape = {
      key: 'ion-cloud-17',
      left: 1,
      top: 2,
      width: 50,
      height: 40,
      imageDataUrl: 'data:image/png;base64,def',
      fillClipPathId: 'ion-cloud-17-fill-clip',
      outerBoundaryPaths: ['M 0 0 L 2 2 Z'],
      outerStroke: 'rgba(255,0,0,0.8)',
      classBoundaryPaths: [
        { stormClass: 2, path: 'M 1 1 L 3 3 Z', stroke: 'rgba(0,255,0,0.5)' },
      ],
      strokeWidth: 0.2,
    }

    const mapped = ionStormCloudPaneShapeToRasterField(shape)
    expect(mapped.clipPaths).toEqual(['M 0 0 L 2 2 Z'])
    expect(mapped.strokePaths.map((entry) => entry.pathKey)).toEqual(['class-2-0', 'outer-0'])
    expect(mapped.strokePaths[0]?.stroke).toBe('rgba(0,255,0,0.5)')
    expect(mapped.strokePaths[1]?.stroke).toBe('rgba(255,0,0,0.8)')
  })
})
