# Planets Console -- user guide

This guide describes the Planets Console web UI as you use it in the browser. Replace the placeholder image paths under [`docs/images/user-guide/`](images/user-guide/) with real screenshots when you capture them.

## Overall layout

The app is a single page with three main regions:

1. **Header** -- top bar: login, game, turn, viewpoint, view mode (tabular or map), and map scale.
2. **Analytics** -- left sidebar: toggles for which analytics are active.
3. **Main area** -- the rest of the window: tables in tabular mode, or the interactive map in map mode.

![Full window: header, analytics bar, and main area](images/user-guide/01-overall-layout.png)

*Screenshot placeholder: full desktop window showing all three regions.*

Below the header, a **shell error bar** may appear when something goes wrong (for example, failed network calls). It lists dismissible messages in a red strip.

![Shell error bar with a sample message](images/user-guide/02-shell-error-bar.png)

*Screenshot placeholder: error bar visible with at least one message and the dismiss control.*

---

## Header

### Login identity

Your **login** is the planets.nu account name used when the app loads game data. It appears as **Login:** next to a small refresh icon.

- Click the refresh icon or use the login flow it opens to **change login**. A modal asks for **Name** and **Password**.
- The password is kept in session memory only (not stored on disk). The **name** may be remembered locally for convenience; passwords are never persisted.
- Until you set a login name, turn data for analytics may not load (the main area will say so).

![Header login label and change-login control](images/user-guide/03-header-login.png)

*Screenshot placeholder: header strip showing Login line and icon.*

### Game

**Game** opens a dropdown listing games available from storage, plus a way to add a game by **id**.

- Pick a game from the list to **load** that game’s info (latest turn and perspectives) from planets.nu.
- Use **Add game (id only)** to enter an id and add it; choosing a game refreshes stored game info.
- While a refresh is in progress, the control may show **Refreshing…**

![Game selector open with list and add-by-id section](images/user-guide/04-header-game.png)

*Screenshot placeholder: game dropdown expanded.*

### Turn

**Turn** is the game year you are analyzing. After game info is loaded, you get a numeric control with down/up steppers and an editable field.

- Valid range is **1** through the latest turn reported for that game.
- Type a number and press **Enter** or blur the field to apply.

![Turn stepper and numeric field](images/user-guide/05-header-turn.png)

*Screenshot placeholder: turn control with arrows and input.*

### Viewpoint

**Viewpoint** is which player’s perspective (slot) the data uses -- for example, which empire’s fog-of-war or ownership view applies.

- After perspectives exist, a dropdown lists player names.
- For games that are **not** finished, only your own slot may be selectable; others can appear greyed/disabled.
- For **finished** games, you can usually switch viewpoint freely.

![Viewpoint dropdown](images/user-guide/06-header-viewpoint.png)

*Screenshot placeholder: viewpoint select with multiple names.*

### View mode and scale

On the **right** of the header:

- **Tabular** / **Map** switches how the main area shows results: stacked tables vs the map.
- **Scale** is a slider that adjusts **map zoom** (logarithmic, same idea as the mouse wheel). It is **disabled in tabular mode** and dimmed.
- A **percentage** next to the slider shows the current zoom (100% = 1x).

![Tabular/Map toggle and Scale slider with percent](images/user-guide/07-header-mode-scale.png)

*Screenshot placeholder: right side of header in map mode with scale active.*

---

## Analytics sidebar

The left column is titled **Analytics**. Each row is one analytic with a **checkbox** and its display name.

- Check an analytic to **include** it in the current view (tabular tables or map layers, depending on mode).
- Analytics that **do not support** the current mode stay visible but look **greyed out**; their checkboxes are disabled until you switch mode.
- The **base map** (planets and connections) is not listed here; when present, it is combined automatically in map mode with your enabled map-capable analytics.

![Analytics list with some enabled and one greyed for current mode](images/user-guide/08-analytics-bar.png)

*Screenshot placeholder: sidebar with multiple analytics, mixed enabled/greyed.*

While the list of analytics is loading from the server, the main area may show **Loading analytics…**

---

## Main area -- tabular mode

With **Tabular** selected, the main area shows **one section per enabled analytic**. Each section has a title (**Analytic:** and the id) and a data table.

- If **no** analytic is enabled, you are prompted to enable at least one in the left bar.
- If game scope is incomplete (no game, turn, or viewpoint), you see a short message instead of tables.
- After scope is set, tables load from the server; pending and error states are shown inline per section.

![Stacked analytic table tiles](images/user-guide/09-tabular-mode.png)

*Screenshot placeholder: two or more table sections stacked.*

---

## Main area -- map mode

With **Map** selected, the main area shows an interactive **graph map** (React Flow): planets as nodes and connections as edges.

### Pan and zoom

- **Drag** on the background to pan.
- **Scroll** (or pinch on a trackpad) to zoom. Zoom is clamped between rough **20%** and **4000%** of base scale.
- The header **Scale** slider stays in sync with the same zoom as the wheel.

![Map with planets and edges, fit to window](images/user-guide/10-map-overview.png)

*Screenshot placeholder: map view with many nodes and edges.*

### Combining analytics

Map layers combine the **base map** (if available) with every **enabled** analytic that supports the map. If nothing map-capable is enabled or no base map exists, you may see a message explaining that.

### Loading states

- Initial load may show **Loading map…**
- If you add another map analytic, a short message **Loading additional map data…** can appear after a brief delay so quick updates do not flash.

### Coordinate grid and warp wells

The map can draw two kinds of **grid lines** aligned to map coordinates (the same integer lines you see in the corner readout when you move the pointer).

- **Warp well grid** -- When you zoom in past a **moderate** level (about **500%** on the header scale, or higher), each planet that is **not** in a **debris disk** shows a grid for its **normal warp well**: every map cell whose **center** lies within **Euclidean distance 3** of the planet’s map cell. Those lines use a **solid** gray so they stay visible.
- **Full background grid** -- When you zoom in **further** (about **1500%** or higher), a **coordinate grid** is drawn across the whole map. It uses the **same** line positions but is drawn **fainter** (30% opacity) so it does not overpower the warp well lines where they overlap.

**Hyperjump** wells are defined in code for distance checks but are **not** drawn on the map today.

For exact rules, thresholds, and file locations, see [Warp wells on the map](design-warp-wells-map.md).

### Planet labels and hover

Planet **dots** sit on the grid; **labels** (and optional detail) follow settings in **Map options** (see below). Moving the pointer near a planet can reveal or emphasize label content depending on implementation.

![Map with planet labels visible](images/user-guide/11-map-labels.png)

*Screenshot placeholder: zoomed area showing labels near planets.*

---

## Map options (bottom sheet)

In map mode, a **Map options** panel slides up from the **bottom-right**. A small **tab** on the lower edge opens it; when open, you can hide it again.

Inside **Map options**, **Planet info** controls how planet labels behave:

- **Planet id**, **Planet name**, **Coordinates** -- toggles for what to include.
- **Detail level** -- **None**, **Low**, **Medium**, or **Debug** (increasing amounts of detail on the label).

![Map options panel open over the map](images/user-guide/12-map-options.png)

*Screenshot placeholder: bottom sheet open showing Planet info controls.*

---

## Login modal

Opening the login flow shows a centered dialog: **Log in to planets.nu**, fields for **Name** and **Password**, **Cancel**, and **Log in**.

- **Escape** closes the dialog (focus returns sensibly to the control that opened it).
- Validation errors appear under the form if submission fails (for example, empty name).

![Login modal centered on dark backdrop](images/user-guide/13-login-modal.png)

*Screenshot placeholder: modal with fields and buttons.*

---

## Quick reference

| Area | What you do |
|------|----------------|
| Login | Set planets.nu identity; required for loading turn data |
| Game | Choose or add game id; refreshes game info |
| Turn | Step or type game year in range |
| Viewpoint | Choose perspective player when allowed |
| Tabular / Map | Switch main content |
| Scale | Map zoom (map mode only) |
| Analytics | Enable/disable each analytic; grey = wrong mode |
| Map options | Planet label content and detail level |
| Zoom | Higher zoom shows warp well grid, then fainter full coordinate grid (see map section) |
| Error bar | Read errors; dismiss per message |

For how the app stores session vs server state, see [Frontend and backend state](design-frontend-and-backend-state.md). For configuration of the server and config files, see [Configuration](configuration.md).
