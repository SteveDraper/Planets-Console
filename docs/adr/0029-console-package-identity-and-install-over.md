# v1 console package identity, install-over, and listen-then-open

Status: accepted

v1 **console package** identity is display name **Planets Console**, `CFBundleIdentifier` `com.github.stevedraper.planets-console`, `AppUserModelID` `SteveDraper.PlanetsConsole`, and Inno `AppId` `{933C1FA0-3D30-4611-AE34-2F7C14C5253B}`. Version is root `pyproject.toml`; Git tags `v*.*.*` must match (`v` + version). Release assets are `Planets-Console-<version>-macos-arm64.dmg` and `Planets-Console-<version>-windows-x64-setup.exe`. The **console data directory** is `~/Library/Application Support/Planets Console/` and `%LOCALAPPDATA%\Planets Console\`.

**Install-over** replaces the **console package** without touching that directory. **Listen-then-open** waits for `GET /health` on `127.0.0.1` (never `localhost`) then opens the default browser. A second activation reuses the **process host** and opens that URL again. Unsigned Gatekeeper / SmartScreen bypass is the v1 README path; Windows 11 Smart App Control with no **Run anyway** is unsupported. User-facing steps live on [User-facing v1 install and upgrade procedure](https://github.com/SteveDraper/Planets-Console/issues/430).

## Considered options

- **Reverse-DNS of a domain we own** -- this repo has no product homepage domain; GitHub Releases is the v1 download site. Rejected `com.github.stevedraper.planets-console` only if a real domain appears later (do not change after first ship).
- **`http://localhost:<port>/`** -- can resolve to `::1` and miss the IPv4 bind. Rejected.
- **Uninstall then install** -- unnecessary with a stable Inno `AppId` / Finder replace; scares people about data. Rejected.
- **Tell users to disable Smart App Control** -- worse than calling that PC unsupported for unsigned v1. Rejected.
- **Run from the DMG / Desktop shortcut** -- ejecting the image "loses" the app; 429 specified Start Menu, not Desktop. Rejected.

## Consequences

- Glossary: **console package** is the installed app, not the download; **install-over** and **listen-then-open** in [CONTEXT.md](../../CONTEXT.md). Do not rename bundle id, `AppUserModelID`, or Inno `AppId` after v1 ships.
- About dialog **Planets Analytic Console** and version `0.1` become **Planets Console** / pyproject (`0.1.0`).
- Icon remains map fog; a placeholder Dock glyph is enough for the **bundler** ticket.

See also: [ADR 0027](0027-console-package-bundler-and-process-host.md), [ADR 0028](0028-console-package-ci-and-installer-wrappers.md), map [v1 Mac and Windows console package](https://github.com/SteveDraper/Planets-Console/issues/423).
