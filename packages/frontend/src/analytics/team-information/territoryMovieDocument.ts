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
    .bottom { grid-column: 2; grid-row: 2; display: flex; flex-direction: column; gap: 10px; padding: 10px 12px; background: #3a3f44; color: #f5f5f4; }
    .scrub-row { display: flex; align-items: flex-end; gap: 12px; }
    .scrubber { flex: 1; min-width: 0; padding: 0 14px; }
    .timeline { position: relative; height: 40px; touch-action: none; cursor: pointer; }
    #ticks { position: absolute; inset: 0; }
    .track { position: absolute; left: 0; right: 0; bottom: 7px; height: 2px; background: #c5c8cc; }
    .tick { position: absolute; bottom: 7px; width: 1px; background: #d5d8dc; transform: translateX(-50%); }
    .tick.minor { height: 6px; }
    .tick.major { height: 12px; background: #f5f5f4; }
    .tick-label { position: absolute; bottom: 22px; transform: translateX(-50%); font-size: 11px; line-height: 1; color: #f5f5f4; }
    .playhead { position: absolute; bottom: 1px; width: 2px; height: 18px; background: #b6ff4a; transform: translateX(-50%); cursor: grab; }
    .playhead::after { content: ""; position: absolute; left: 50%; top: -3px; width: 10px; height: 10px; transform: translateX(-50%); border-radius: 50%; background: #b6ff4a; }
    .speed { display: flex; align-items: center; gap: 6px; flex: none; }
    .speed-label { font-size: 13px; }
    .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    button, label { font: inherit; }
    .bottom button { display: inline-flex; align-items: center; justify-content: center; padding: 0; border: 1px solid #1c1f22; border-radius: 8px; background: linear-gradient(180deg, #f4f5f6 0%, #d7dbdf 46%, #b7bcc1 100%); box-shadow: inset 0 1px 0 #ffffff, inset 0 -1px 0 #8d9298; cursor: pointer; }
    .controls button { width: 42px; height: 42px; }
    .speed button { width: 28px; height: 28px; }
    .bottom button svg { display: block; background: none; }
    .controls button svg { width: 22px; height: 22px; }
    .speed button svg { width: 14px; height: 14px; }
    #back-to-start, #frame-back, #frame-forward { color: #067a99; }
    #play, #pause { color: #3d7a00; }
    #speed-down, #speed-up { color: #1c1f22; }
    .bottom button:disabled { opacity: 0.45; cursor: default; }
    .frame { grid-column: 2; grid-row: 1; position: relative; min-width: 0; min-height: 0; background: #000; }
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
      <svg id="map" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet"></svg>
    </div>
    <div class="bottom">
      <div class="scrub-row">
        <div class="scrubber">
          <div id="timeline" class="timeline">
            <div id="ticks"></div>
            <div class="track"></div>
            <div id="playhead" class="playhead"></div>
          </div>
        </div>
        <div class="speed">
          <span class="speed-label">Speed</span>
          <button type="button" id="speed-down" aria-label="Slower">${icon('M5 11h14v2H5z')}</button>
          <button type="button" id="speed-up" aria-label="Faster">${icon('M11 5h2v14h-2zM5 11h14v2H5z')}</button>
        </div>
      </div>
      <div class="controls">
        <button type="button" id="back-to-start" aria-label="Back to turn 1">${icon('M6 5.5h2.2v13H6v-13zm12.2 0L8.8 12l9.4 6.5v-13z')}</button>
        <button type="button" id="frame-back" aria-label="One frame back">${icon('M14 5.5 5.5 12 14 18.5zM16.3 5.5h2.2v13h-2.2z')}</button>
        <button type="button" id="play" aria-label="Play">${icon('M7.5 5.5v13l11-6.5-11-6.5z')}</button>
        <button type="button" id="pause" aria-label="Pause">${icon('M6 5.5h3.4v13H6v-13zm8.6 0H18v13h-3.4v-13z')}</button>
        <button type="button" id="frame-forward" aria-label="One frame forward">${icon('M5.5 5.5h2.2v13H5.5zM10 5.5v13l8.5-6.5L10 5.5z')}</button>
      </div>
    </div>
  </main>
  <script type="application/json" id="territory-movie-payload">${json}</script>
  <script>
const runtime = (${runtime})();
runtime.boot(document, JSON.parse(document.getElementById("territory-movie-payload").textContent));
  </script>
</body>
</html>
`
}
