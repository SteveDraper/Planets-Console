# v1 console package CI is native macos-15 / windows-2025, tag plus dispatch, hdiutil and Inno

Status: accepted

v1 **console package** GitHub Release assets are built on pinned GitHub-hosted runners (`macos-15` Apple Silicon, `windows-2025` x64), not `*-latest`. One workflow runs on version-tag push and on `workflow_dispatch`: **bundler**, **installer wrapper**, then `gh release create` (or reattach) in the same run. Do not use `on: release: published` as the primary trigger -- `GITHUB_TOKEN` creating a Release will not start a second `release:` workflow. Mac wrap is Apple `hdiutil` UDZO with an Applications symlink. Windows wrap is Inno Setup `PrivilegesRequired=lowest` (per-user setup `.exe` to `%LocalAppData%\Programs`, ARP and Start Menu; **console data directory** is not in `[Files]` or uninstall-delete). Unsigned is the uploaded file.

User OS is not the runner OS: Apple Silicon macOS 11 through 15 and 26, Windows 10 and 11 x64. Freeze sets `MACOSX_DEPLOYMENT_TARGET` to 11 so the Mac floor matches the `macosx_11_0` wheels.

## Considered options

- **`macos-latest` / `windows-latest`** -- retargets when GitHub moves the alias (`macos-latest` already tracks macOS 26). Rejected so freeze hosts stay stable.
- **`macos-14`** -- arm64, but retires 2026-11-02. Rejected.
- **`on: release: types: [published]`** -- needs a human or non-`GITHUB_TOKEN` publisher; a workflow that also creates the Release will not chain. Rejected as the primary trigger.
- **create-dmg / dmgbuild** -- extra CI dependency; headless `--skip-jenkins` drops Finder layout and leaves `hdiutil` plus a symlink. Rejected.
- **WiX MSI** -- image has WiX 3.14, not the v4+ `Scope=perUser` CLI; MSI is not the usual non-technical Windows shape. Rejected.
- **NSIS** -- not on the runner; third script language. Rejected.
- **Zip of the PyInstaller onedir** -- not an installer. Rejected.

## Consequences

- Glossary: **installer wrapper** in [CONTEXT.md](../../CONTEXT.md). The **bundler** (PyInstaller) still does not emit `.dmg` or a Windows setup `.exe`.
- Tag glob and Release asset names: [ADR 0029](0029-console-package-identity-and-install-over.md).
- Research notes (not on `main`): `docs/research/console-package-github-actions.md`, `docs/research/console-package-installer-wrappers.md`.

See also: [Choose v1 CI and installer wrappers](https://github.com/SteveDraper/Planets-Console/issues/429), [ADR 0027](0027-console-package-bundler-and-process-host.md), map [v1 Mac and Windows console package](https://github.com/SteveDraper/Planets-Console/issues/423).
