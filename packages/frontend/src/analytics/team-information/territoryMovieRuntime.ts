/**
 * Page runtime for one Territory movie document.
 * This function must not read module bindings: the HTML file embeds its source
 * and runs that copy from `file://`.
 */
export function createTerritoryMovieRuntime() {
  const PLAY_STEP_MS = 1000
  const MIN_FRAME_PERIOD_MS = 100
  const MAX_FRAME_PERIOD_MS = 5000
  const SVG_NS = 'http://www.w3.org/2000/svg'
  const DOT_FILL = '#9ca3af'

  type Vertex = { dx: number; dy: number }
  type Ring = { groupId: number; vertices: Vertex[] }
  type LegendEntry = { id: number; name: string | null }
  type Rectangle = { left: number; bottom: number; width: number; height: number }
  type SelectionName = 'players' | 'teams'
  type SelectionState = {
    checked: Record<number, boolean>
    indexByOwnerId: Record<number, number>
    nextIndex: number
  }
  type MovieState = {
    byTeam: boolean
    ownedPlanetsOnly: boolean
    frame: number
    selections: { players: SelectionState; teams: SelectionState }
  }
  type PlanetRow = { id: number; x: number; y: number; firstTurn: number }
  type PlanetDots = { valid: false; rows: PlanetRow[] } | { valid: true; rows: PlanetRow[] }
  type Movie = {
    turn: number
    rectangle: Rectangle
    sections: Ring[][][]
    planets: PlanetDots
    players: LegendEntry[]
    teams: LegendEntry[]
    palette: string[]
  }

  function emptySelection(): SelectionState {
    return { checked: {}, indexByOwnerId: {}, nextIndex: 0 }
  }

  function initialState(): MovieState {
    return {
      byTeam: false,
      ownedPlanetsOnly: false,
      frame: 1,
      selections: { players: emptySelection(), teams: emptySelection() },
    }
  }

  function isSelection(selection: string): selection is SelectionName {
    return selection === 'players' || selection === 'teams'
  }

  function hasIndex(selection: SelectionState, ownerId: number): boolean {
    return Object.prototype.hasOwnProperty.call(selection.indexByOwnerId, ownerId)
  }

  function toggleOwner(state: MovieState, selection: SelectionName, ownerId: number): MovieState {
    if (!isSelection(selection)) return state
    const current = state.selections[selection]
    const checked = { ...current.checked }
    const indexByOwnerId = { ...current.indexByOwnerId }
    let nextIndex = current.nextIndex
    if (checked[ownerId] === true) {
      delete checked[ownerId]
    } else if (!hasIndex(current, ownerId)) {
      indexByOwnerId[ownerId] = nextIndex
      nextIndex += 1
      checked[ownerId] = true
    } else {
      checked[ownerId] = true
    }
    return {
      ...state,
      selections: {
        ...state.selections,
        [selection]: { checked, indexByOwnerId, nextIndex },
      },
    }
  }

  function setByTeam(state: MovieState, value: boolean): MovieState {
    if (state.byTeam === value) return state
    return { ...state, byTeam: value }
  }

  function setOwnedPlanetsOnly(state: MovieState, value: boolean): MovieState {
    if (state.ownedPlanetsOnly === value) return state
    return { ...state, ownedPlanetsOnly: value }
  }

  function setFrame(state: MovieState, frame: number, maxTurn: number): MovieState {
    if (!Number.isInteger(frame) || !Number.isInteger(maxTurn) || maxTurn < 1) return state
    const next = Math.min(maxTurn, Math.max(1, frame))
    if (state.frame === next) return state
    return { ...state, frame: next }
  }

  function selectionKey(state: MovieState): SelectionName {
    return state.byTeam ? 'teams' : 'players'
  }

  function sectionIndex(byTeam: boolean, ownedPlanetsOnly: boolean): number {
    if (byTeam) return ownedPlanetsOnly ? 2 : 0
    return ownedPlanetsOnly ? 3 : 1
  }

  function colorIndex(state: MovieState, selection: SelectionName, ownerId: number): number | null {
    const current = state.selections[selection]
    if (!hasIndex(current, ownerId)) return null
    return current.indexByOwnerId[ownerId] ?? null
  }

  function legendLabel(entry: LegendEntry): string {
    const name = typeof entry.name === 'string' ? entry.name.trim() : ''
    return name === '' ? String(entry.id) : name
  }

  function legendRows(state: MovieState, owners: readonly LegendEntry[], selection: SelectionName) {
    const current = state.selections[selection]
    return owners.map((owner) => ({
      id: owner.id,
      label: legendLabel(owner),
      index: hasIndex(current, owner.id) ? current.indexByOwnerId[owner.id] : null,
      checked: current.checked[owner.id] === true,
    }))
  }

  function checkedIds(state: MovieState, selection: SelectionName): Set<number> {
    const ids = new Set<number>()
    const checked = state.selections[selection].checked
    for (const key of Object.keys(checked)) {
      if (checked[Number(key)] === true) ids.add(Number(key))
    }
    return ids
  }

  function readU16(view: DataView, offset: number): number | null {
    if (offset + 2 > view.byteLength) return null
    return view.getUint16(offset, true)
  }

  function decodeRings(bytes: Uint8Array, turnCount: number): Ring[][][] | null {
    if (!Number.isInteger(turnCount) || turnCount < 1) return null
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    let offset = 0
    const sections: Ring[][][] = []
    for (let section = 0; section < 4; section += 1) {
      const frames: Ring[][] = []
      for (let turn = 0; turn < turnCount; turn += 1) {
        const count = readU16(view, offset)
        if (count == null) return null
        offset += 2
        const components: Ring[] = []
        for (let component = 0; component < count; component += 1) {
          const groupId = readU16(view, offset)
          const vertexCount = readU16(view, offset + 2)
          if (groupId == null || vertexCount == null) return null
          offset += 4
          const vertices: Vertex[] = []
          for (let vertex = 0; vertex < vertexCount; vertex += 1) {
            const dx = readU16(view, offset)
            const dy = readU16(view, offset + 2)
            if (dx == null || dy == null) return null
            offset += 4
            vertices.push({ dx, dy })
          }
          components.push({ groupId, vertices })
        }
        frames.push(components)
      }
      sections.push(frames)
    }
    return sections
  }

  function emptySections(turnCount: number): Ring[][][] {
    return [0, 1, 2, 3].map(() => Array.from({ length: turnCount }, () => []))
  }

  function decodePlanets(bytes: Uint8Array): PlanetDots {
    const invalid: PlanetDots = { valid: false, rows: [] }
    if (bytes.byteLength < 2) return invalid
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
    const count = view.getUint16(0, true)
    if (bytes.byteLength !== 2 + count * 8) return invalid
    const rows: PlanetRow[] = []
    const seen = new Set<number>()
    for (let index = 0; index < count; index += 1) {
      const offset = 2 + index * 8
      const id = view.getUint16(offset, true)
      if (seen.has(id)) return invalid
      seen.add(id)
      rows.push({
        id,
        x: view.getUint16(offset + 2, true),
        y: view.getUint16(offset + 4, true),
        firstTurn: view.getUint16(offset + 6, true),
      })
    }
    return { valid: true, rows }
  }

  function visibleDots(planets: PlanetDots, frame: number): PlanetRow[] {
    if (!planets.valid) return []
    return planets.rows.filter((row) => frame >= row.firstTurn)
  }

  function framePaths(
    components: readonly Ring[],
    rectangle: Rectangle,
    selected: ReadonlySet<number>
  ): { groupId: number; d: string }[] {
    const groups: { groupId: number; subpaths: string[] }[] = []
    const indexByGroup = new Map<number, { groupId: number; subpaths: string[] }>()
    for (const component of components) {
      if (!selected.has(component.groupId) || component.vertices.length === 0) continue
      let group = indexByGroup.get(component.groupId)
      if (group == null) {
        group = { groupId: component.groupId, subpaths: [] }
        indexByGroup.set(component.groupId, group)
        groups.push(group)
      }
      const commands = component.vertices.map((vertex, vertexIndex) => {
        const x = rectangle.left + vertex.dx / 10
        const y = rectangle.bottom + vertex.dy / 10
        return `${vertexIndex === 0 ? 'M' : 'L'}${x} ${y}`
      })
      commands.push('Z')
      group.subpaths.push(commands.join(''))
    }
    return groups.map((group) => ({ groupId: group.groupId, d: group.subpaths.join('') }))
  }

  function dotRadius(viewBoxWidth: number, cssWidth: number): number {
    if (!(viewBoxWidth > 0) || !(cssWidth > 0)) return 0
    return (2 * viewBoxWidth) / cssWidth
  }

  /** Faster shortens the period by 10 percent. Slower lengthens it. */
  function nextFramePeriod(period: number, faster: boolean): number {
    const scaled = period * (faster ? 0.9 : 1.1)
    if (scaled < MIN_FRAME_PERIOD_MS) return MIN_FRAME_PERIOD_MS
    if (scaled > MAX_FRAME_PERIOD_MS) return MAX_FRAME_PERIOD_MS
    return scaled
  }

  /** CSS width of the viewBox after it meets inside the SVG element. */
  function fittedCssWidth(
    rectangle: Rectangle,
    cssWidth: number,
    cssHeight: number
  ): number {
    if (
      !(rectangle.width > 0) ||
      !(rectangle.height > 0) ||
      !(cssWidth > 0) ||
      !(cssHeight > 0)
    ) {
      return 0
    }
    const viewAspect = rectangle.width / rectangle.height
    const boxAspect = cssWidth / cssHeight
    return boxAspect > viewAspect ? cssHeight * viewAspect : cssWidth
  }

  function viewBoxFor(rectangle: Rectangle): string {
    const top = -(rectangle.bottom + rectangle.height)
    return `${rectangle.left} ${top} ${rectangle.width} ${rectangle.height}`
  }

  function lockSidebarWidth(doc: Document): void {
    const sidebar = doc.querySelector('.sidebar')
    const measures = doc.querySelector('.measures')
    if (!(sidebar instanceof HTMLElement) || !(measures instanceof HTMLElement)) return
    const width = measures.scrollWidth
    if (width > 0) sidebar.style.width = `${width}px`
  }

  function required(doc: Document, id: string): HTMLElement {
    const element = doc.getElementById(id)
    if (element == null) {
      throw new Error(`Territory movie page is missing ${id}.`)
    }
    return element
  }

  async function inflateBase64(encoded: string): Promise<Uint8Array> {
    const binary = atob(encoded)
    const bytes = new Uint8Array(binary.length)
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index)
    }
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(bytes)
        controller.close()
      },
    }).pipeThrough(new DecompressionStream('gzip'))
    const buffer = await new Response(stream).arrayBuffer()
    return new Uint8Array(buffer)
  }

  function start(doc: Document, movie: Movie): void {
    const backButton = required(doc, 'back-to-start')
    const playButton = required(doc, 'play')
    const pauseButton = required(doc, 'pause')
    const forwardButton = required(doc, 'frame-forward')
    const backFrameButton = required(doc, 'frame-back')
    const byTeamInput = required(doc, 'by-team') as HTMLInputElement
    const ownedInput = required(doc, 'owned-only') as HTMLInputElement
    const map = required(doc, 'map')
    const legend = required(doc, 'legend')
    const timeline = required(doc, 'timeline')
    const ticks = required(doc, 'ticks')
    const playhead = required(doc, 'playhead')
    const slowerButton = required(doc, 'speed-down')
    const fasterButton = required(doc, 'speed-up')

    let state = initialState()
    let playing = false
    let timer = 0
    let framePeriod = PLAY_STEP_MS
    let dragging = false

    lockSidebarWidth(doc)
    map.setAttribute('viewBox', viewBoxFor(movie.rectangle))
    const flip = doc.createElementNS(SVG_NS, 'g')
    flip.setAttribute('transform', 'scale(1,-1)')
    const rings = doc.createElementNS(SVG_NS, 'g')
    const dots = doc.createElementNS(SVG_NS, 'g')
    flip.append(rings, dots)
    map.replaceChildren(flip)

    function renderTransport(): void {
      playButton.toggleAttribute('disabled', playing || state.frame >= movie.turn)
      pauseButton.toggleAttribute('disabled', !playing)
      forwardButton.toggleAttribute('disabled', state.frame >= movie.turn)
      backFrameButton.toggleAttribute('disabled', state.frame <= 1)
    }

    function renderFrame(): void {
      doc.title = String(state.frame)
      const selection = selectionKey(state)
      const section = movie.sections[sectionIndex(state.byTeam, state.ownedPlanetsOnly)] ?? []
      const components = section[state.frame - 1] ?? []
      const paths = framePaths(components, movie.rectangle, checkedIds(state, selection))
      rings.replaceChildren()
      for (const path of paths) {
        const element = doc.createElementNS(SVG_NS, 'path')
        const index = colorIndex(state, selection, path.groupId)
        const fill = index == null ? 'none' : (movie.palette[index] ?? 'none')
        element.setAttribute('data-group-id', String(path.groupId))
        element.setAttribute('d', path.d)
        element.setAttribute('fill', fill)
        element.setAttribute('fill-opacity', '1')
        element.setAttribute('fill-rule', 'evenodd')
        rings.append(element)
      }
      const bounds = map.getBoundingClientRect()
      const radius = dotRadius(
        movie.rectangle.width,
        fittedCssWidth(movie.rectangle, bounds.width, bounds.height)
      )
      dots.replaceChildren()
      for (const row of visibleDots(movie.planets, state.frame)) {
        const circle = doc.createElementNS(SVG_NS, 'circle')
        circle.setAttribute('cx', String(row.x))
        circle.setAttribute('cy', String(row.y))
        circle.setAttribute('r', String(radius))
        circle.setAttribute('fill', DOT_FILL)
        dots.append(circle)
      }
      renderPlayhead()
    }

    function frameRatio(frame: number): number {
      if (movie.turn <= 1) return 0
      return (frame - 1) / (movie.turn - 1)
    }

    function renderPlayhead(): void {
      playhead.style.left = `${frameRatio(state.frame) * 100}%`
    }

    function renderTicks(): void {
      ticks.replaceChildren()
      for (let turn = 1; turn <= movie.turn; turn += 1) {
        const numbered = turn === 1 || turn % 10 === 0
        const tick = doc.createElement('span')
        tick.className = numbered ? 'tick major' : 'tick minor'
        tick.style.left = `${frameRatio(turn) * 100}%`
        ticks.append(tick)
        if (!numbered) continue
        const label = doc.createElement('span')
        label.className = 'tick-label'
        label.textContent = String(turn)
        label.style.left = `${frameRatio(turn) * 100}%`
        ticks.append(label)
      }
    }

    function seek(frame: number): void {
      const next = Math.min(movie.turn, Math.max(1, Math.round(frame)))
      if (next === state.frame) return
      state = setFrame(state, next, movie.turn)
      renderFrame()
      if (playing && state.frame >= movie.turn) {
        pause()
        return
      }
      if (playing) armTimer()
      renderTransport()
    }

    function seekFromClientX(clientX: number): void {
      const rect = timeline.getBoundingClientRect()
      if (!(rect.width > 0)) return
      const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
      const frame = movie.turn <= 1 ? 1 : 1 + ratio * (movie.turn - 1)
      seek(frame)
    }

    function clientXFrom(event: Event): number | null {
      if (!('clientX' in event)) return null
      const clientX = event.clientX
      return typeof clientX === 'number' ? clientX : null
    }

    function renderLegend(): void {
      const selection = selectionKey(state)
      const owners = selection === 'teams' ? movie.teams : movie.players
      legend.replaceChildren()
      legend.setAttribute('aria-label', selection === 'teams' ? 'League teams' : 'Players')
      for (const row of legendRows(state, owners, selection)) {
        const item = doc.createElement('li')
        const label = doc.createElement('label')
        const input = doc.createElement('input')
        input.type = 'checkbox'
        input.checked = row.checked
        input.dataset.ownerId = String(row.id)
        label.append(input)
        if (row.checked && row.index != null && movie.palette[row.index] != null) {
          const swatch = doc.createElement('span')
          swatch.className = 'swatch'
          swatch.dataset.colorIndex = String(row.index)
          swatch.style.backgroundColor = movie.palette[row.index] ?? ''
          label.append(swatch)
        }
        const text = doc.createElement('span')
        text.textContent = row.label
        label.append(text)
        item.append(label)
        legend.append(item)
      }
    }

    function armTimer(): void {
      if (timer !== 0) clearInterval(timer)
      timer = window.setInterval(() => {
        if (state.frame >= movie.turn) {
          pause()
          return
        }
        state = setFrame(state, state.frame + 1, movie.turn)
        renderFrame()
        if (state.frame >= movie.turn) {
          pause()
          return
        }
        renderTransport()
      }, framePeriod)
    }

    function pause(): void {
      playing = false
      if (timer !== 0) {
        clearInterval(timer)
        timer = 0
      }
      renderTransport()
    }

    function play(): void {
      if (state.frame >= movie.turn) return
      playing = true
      armTimer()
      renderTransport()
    }

    function step(delta: number): void {
      const before = state.frame
      state = setFrame(state, state.frame + delta, movie.turn)
      if (state.frame === before) return
      renderFrame()
      if (playing && state.frame >= movie.turn) {
        pause()
        return
      }
      if (playing) armTimer()
      renderTransport()
    }

    backButton.addEventListener('click', () => {
      state = setFrame(state, 1, movie.turn)
      renderFrame()
      if (playing) armTimer()
      renderTransport()
    })
    playButton.addEventListener('click', () => {
      play()
    })
    pauseButton.addEventListener('click', () => {
      pause()
    })
    forwardButton.addEventListener('click', () => {
      step(1)
    })
    backFrameButton.addEventListener('click', () => {
      step(-1)
    })
    slowerButton.addEventListener('click', () => {
      framePeriod = nextFramePeriod(framePeriod, false)
      if (playing) armTimer()
    })
    fasterButton.addEventListener('click', () => {
      framePeriod = nextFramePeriod(framePeriod, true)
      if (playing) armTimer()
    })
    timeline.addEventListener('pointerdown', (event) => {
      const clientX = clientXFrom(event)
      if (clientX == null) return
      dragging = true
      if (
        'pointerId' in event &&
        typeof event.pointerId === 'number' &&
        typeof timeline.setPointerCapture === 'function'
      ) {
        try {
          timeline.setPointerCapture(event.pointerId)
        } catch {
          dragging = true
        }
      }
      seekFromClientX(clientX)
    })
    timeline.addEventListener('pointermove', (event) => {
      if (!dragging) return
      const clientX = clientXFrom(event)
      if (clientX == null) return
      seekFromClientX(clientX)
    })
    const endDrag = (): void => {
      dragging = false
    }
    timeline.addEventListener('pointerup', endDrag)
    timeline.addEventListener('pointercancel', endDrag)
    byTeamInput.addEventListener('change', () => {
      state = setByTeam(state, byTeamInput.checked)
      renderLegend()
      renderFrame()
    })
    ownedInput.addEventListener('change', () => {
      state = setOwnedPlanetsOnly(state, ownedInput.checked)
      renderFrame()
    })
    legend.addEventListener('change', (event) => {
      const target = event.target
      if (!(target instanceof HTMLInputElement)) return
      const ownerId = Number(target.dataset.ownerId)
      if (!Number.isInteger(ownerId)) return
      state = toggleOwner(state, selectionKey(state), ownerId)
      renderLegend()
      renderFrame()
    })
    window.addEventListener('resize', () => {
      renderFrame()
    })

    byTeamInput.checked = false
    ownedInput.checked = false
    renderTicks()
    renderLegend()
    renderFrame()
    renderTransport()
    requestAnimationFrame(() => {
      renderFrame()
    })
  }

  async function boot(
    doc: Document,
    payload: {
      turn: number
      rectangle: Rectangle
      rings: string
      planets: string
      players: LegendEntry[]
      teams: LegendEntry[]
      palette: string[]
    }
  ): Promise<void> {
    const rings = await inflateBase64(payload.rings)
    const planets = await inflateBase64(payload.planets)
    const sections = decodeRings(rings, payload.turn) ?? emptySections(payload.turn)
    start(doc, {
      turn: payload.turn,
      rectangle: payload.rectangle,
      sections,
      planets: decodePlanets(planets),
      players: payload.players,
      teams: payload.teams,
      palette: payload.palette,
    })
  }

  return {
    PLAY_STEP_MS,
    MIN_FRAME_PERIOD_MS,
    MAX_FRAME_PERIOD_MS,
    nextFramePeriod,
    initialState,
    toggleOwner,
    setByTeam,
    setOwnedPlanetsOnly,
    setFrame,
    sectionIndex,
    colorIndex,
    legendRows,
    decodeRings,
    decodePlanets,
    visibleDots,
    framePaths,
    dotRadius,
    fittedCssWidth,
    viewBoxFor,
    start,
    boot,
  }
}
