import type { TerritoryMovieResponse } from '../../api/bff'
import { createTerritoryMovieRuntime } from './territoryMovieRuntime'

export type TerritoryMovieDocumentPayload = TerritoryMovieResponse & {
  palette: readonly string[]
}

function jsonForScript(value: unknown): string {
  return JSON.stringify(value).replace(/</g, '\\u003c')
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
    body { margin: 0; background: #f4f1ea; color: #1c1917; font: 16px/1.4 system-ui, sans-serif; }
    main { max-width: 960px; margin: 0 auto; padding: 12px; }
    .controls { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
    button, label { font: inherit; }
    button { padding: 6px 10px; border: 1px solid #d6d3d1; border-radius: 999px; background: #fffcf7; cursor: pointer; }
    button:disabled { opacity: 0.45; cursor: default; }
    .frame { position: relative; background: #000; }
    h1 { position: absolute; z-index: 1; margin: 0; top: 8px; left: 12px; color: #e5e7eb; font-size: 20px; font-weight: 600; pointer-events: none; }
    svg { display: block; width: 100%; height: auto; background: #000; pointer-events: none; }
    #legend { list-style: none; margin: 12px 0 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
    #legend label { display: flex; align-items: center; gap: 6px; }
    .swatch { width: 12px; height: 12px; border-radius: 2px; }
  </style>
</head>
<body>
  <main>
    <div class="controls">
      <button type="button" id="back-to-start">Back to turn 1</button>
      <button type="button" id="play">Play</button>
      <button type="button" id="pause">Pause</button>
      <button type="button" id="frame-forward">One frame forward</button>
      <button type="button" id="frame-back">One frame back</button>
      <label><input type="checkbox" id="by-team"> By team</label>
      <label><input type="checkbox" id="owned-only"> Owned planets only</label>
    </div>
    <div class="frame">
      <h1 id="frame-title"></h1>
      <svg id="map" xmlns="http://www.w3.org/2000/svg"></svg>
    </div>
    <ul id="legend"></ul>
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
