import type { TerritoryMovieResponse } from '../../api/bff'
import { createTerritoryMovieRuntime } from './territoryMovieRuntime'

export type TerritoryMovieDocumentPayload = TerritoryMovieResponse & {
  palette: readonly string[]
}

function jsonForScript(value: unknown): string {
  return JSON.stringify(value).replace(/</g, '\\u003c')
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function ownerLabel(entry: { id: number; name: string | null }): string {
  const name = entry.name?.trim() ?? ''
  return name === '' ? String(entry.id) : name
}

function icon(path: string): string {
  return `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="${path}"/></svg>`
}

/** Hidden rows whose width is the wider of the two legends and the section switches. */
function sidebarMeasures(payload: TerritoryMovieDocumentPayload): string {
  const switches = ['By team', 'Owned planets only'].map(
    (label) =>
      `<div class="switch-measure"><span class="box"></span><span>${escapeHtml(label)}</span></div>`
  )
  const owners = [...payload.players, ...payload.teams].map(
    (entry) =>
      `<div class="owner-measure"><span class="box"></span><span class="swatch"></span><span>${escapeHtml(ownerLabel(entry))}</span></div>`
  )
  return `<div class="measures" aria-hidden="true">${switches.join('')}${owners.join('')}</div>`
}

/** One HTML document. The page script is the embedded movie runtime, with no imports. */
export function buildTerritoryMovieDocument(payload: TerritoryMovieDocumentPayload): string {
  const json = jsonForScript(payload)
  const runtime = createTerritoryMovieRuntime.toString()
  return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Territory movie</title>
  <style>
    html, body { height: 100%; }
    body { margin: 0; height: 100vh; height: 100dvh; overflow: hidden; background: #f4f1ea; color: #1c1917; font: 16px/1.4 system-ui, sans-serif; }
    main { box-sizing: border-box; display: grid; grid-template-columns: max-content minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) auto; gap: 12px; height: 100%; padding: 12px; }
    .sidebar { grid-column: 1; grid-row: 1; position: relative; display: flex; flex-direction: column; gap: 8px; min-height: 0; overflow: auto; box-sizing: content-box; padding: 10px 12px; background: #3a3f44; color: #f5f5f4; }
    .measures { position: absolute; left: 0; top: 0; width: max-content; visibility: hidden; white-space: nowrap; pointer-events: none; }
    .switch-measure, .owner-measure { display: flex; align-items: center; gap: 6px; width: max-content; white-space: nowrap; }
    .owner-measure { padding-left: 1.25rem; }
    .box { width: 16px; height: 16px; flex: none; }
    .controls { grid-column: 2; grid-row: 2; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    button, label { font: inherit; }
    .controls button { display: inline-flex; align-items: center; justify-content: center; width: 42px; height: 42px; padding: 0; border: 1px solid #22262a; border-radius: 8px; background: linear-gradient(180deg, #6b7076 0%, #4c5156 48%, #3c4044 100%); box-shadow: inset 0 1px 0 #a0a6ab, inset 0 -1px 0 #2c2f33; cursor: pointer; }
    .controls button svg { width: 22px; height: 22px; display: block; background: none; }
    #back-to-start, #frame-back, #frame-forward { color: #3ecbff; }
    #play, #pause { color: #b6ff4a; }
    .controls button:disabled { opacity: 0.45; cursor: default; }
    .frame { grid-column: 2; grid-row: 1; position: relative; min-width: 0; min-height: 0; background: #000; }
    h1 { position: absolute; z-index: 1; margin: 0; top: 8px; left: 12px; color: #e5e7eb; font-size: 20px; font-weight: 600; pointer-events: none; }
    #map { display: block; width: 100%; height: 100%; background: #000; pointer-events: none; }
    #legend { list-style: none; margin: 0; padding: 0 0 0 1.25rem; display: flex; flex-direction: column; gap: 6px; }
    #legend label { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
    .swatch { width: 12px; height: 12px; border-radius: 2px; flex: none; }
  </style>
</head>
<body>
  <main>
    <aside class="sidebar">
      ${sidebarMeasures(payload)}
      <label><input type="checkbox" id="by-team"> By team</label>
      <label><input type="checkbox" id="owned-only"> Owned planets only</label>
      <ul id="legend"></ul>
    </aside>
    <div class="frame">
      <h1 id="frame-title"></h1>
      <svg id="map" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet"></svg>
    </div>
    <div class="controls">
      <button type="button" id="back-to-start" aria-label="Back to turn 1">${icon('M6 5.5h2.2v13H6v-13zm12.2 0L8.8 12l9.4 6.5v-13z')}</button>
      <button type="button" id="frame-back" aria-label="One frame back">${icon('M17 5.5 6.5 12 17 18.5v-13z')}</button>
      <button type="button" id="play" aria-label="Play">${icon('M7.5 5.5v13l11-6.5-11-6.5z')}</button>
      <button type="button" id="pause" aria-label="Pause">${icon('M6 5.5h3.4v13H6v-13zm8.6 0H18v13h-3.4v-13z')}</button>
      <button type="button" id="frame-forward" aria-label="One frame forward">${icon('M5.5 5.5v13L15 12 5.5 5.5zM16.2 5.5H18.4v13h-2.2v-13z')}</button>
    </div>
  </main>
  <script type="application/json" id="territory-movie-payload">${json}</script>
  <script type="module">
const runtime = (${runtime})();
runtime.boot(document, JSON.parse(document.getElementById("territory-movie-payload").textContent));
  </script>
</body>
</html>
`
}
