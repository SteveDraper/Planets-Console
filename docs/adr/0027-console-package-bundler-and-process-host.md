# v1 console package is PyInstaller onedir plus a thin process host

Status: accepted

v1 **console package** on macOS Apple Silicon and Windows x64 is produced by one **bundler**: PyInstaller 6.15+, onedir, `--windowed`. The running app is a thin **process host** (regular Mac `.app` + AppKit; Windows GUI subsystem + unowned HWND for a taskbar button) that translates OS Quit/Close into uvicorn `should_exit`. The SPA stays in the default browser. **Single-instance**: a second activation reuses that process (Windows: per-user lock file); two servers must not share one **console data directory**.

Unsigned v1 is acceptable. No Electron/Tauri SPA window. No tray in v1. Installer wrappers, CI, and user-facing procedure text are later tickets. Launch-wait and reopen copy are [User-facing v1 install and upgrade procedure](https://github.com/SteveDraper/Planets-Console/issues/430); the **process host** must still handle Mac reopen without creating a native window.

## Considered options

- **Nuitka 4.2+ standalone** -- works on both OSes; slower CI compile, AGPL-with-exception, fewer FastAPI/uvicorn collect hooks. Rejected for v1.
- **cx_Freeze 8.5+ onedir** -- no Windows/macOS onefile; `bdist_msi` / `bdist_dmg` mix bundling with installer format. Rejected so the bundler is not the wrapper.
- **Briefcase GUI bundle** -- `.app`+DMG shape, but pip-into-bundle (not a uv-workspace collect) and the GUI path leans at a toolkit window. Rejected.
- **Split bundlers / py2app** -- py2app is macOS-only; py2exe was not verified for Python 3.14. One stack meets the map.
- **Electron or Tauri** -- rejected; Dock/taskbar identity does not need a webview.
- **PyInstaller onefile** -- extra extract on every launch; uvicorn SIGINT double-fire on the onefile parent. Rejected for onedir.
- **Windows second process** -- two uvicorn binds and two writers on the **file backend**. Rejected for **single-instance**.
- **Global named mutex only** -- Microsoft documents pre-create attacks; rejected in favor of a per-user lock file (mutex optional as well).

## Consequences

- Glossary: **bundler**, **process host**, **single-instance** in [CONTEXT.md](../../CONTEXT.md). Do not call the bundler **freeze** (that is **compute diagnostic mode**). Do not call the **process host** bare **host** (VGA Planets rules).
- First implementation may still need hidden-imports (OR-Tools SAT, uvicorn factory string) and a Windows VC++ redistributable; that is not a second bundler.
- Research notes (not on `main`): `docs/research/console-package-freeze-stack.md`, `docs/research/console-package-process-host.md`.

See also: [Choose v1 freeze and process host](https://github.com/SteveDraper/Planets-Console/issues/428), map [v1 Mac and Windows console package](https://github.com/SteveDraper/Planets-Console/issues/423).
