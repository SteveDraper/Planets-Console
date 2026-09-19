# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the v1 console package (onedir, windowed)."""

from __future__ import annotations

import sys
from pathlib import Path

spec_dir = Path(SPECPATH).resolve()
repo_root = spec_dir.parent
if str(spec_dir) not in sys.path:
    sys.path.insert(0, str(spec_dir))

from bundle_console_package import (
    WORK_DIR_RELATIVE,
    analysis_binaries,
    collect_policy,
    macos_info_plist,
    prepare_placeholder_icon,
    pyinstaller_scripts_without,
    sat_worker_collect_policy,
    validate_inputs,
)

policy = collect_policy(repo_root)
worker_policy = sat_worker_collect_policy(repo_root)
validate_inputs(repo_root, policy, worker_policy)
work_dir = repo_root / WORK_DIR_RELATIVE
work_dir.mkdir(parents=True, exist_ok=True)
icon_path = prepare_placeholder_icon(work_dir)
icon = str(icon_path) if icon_path is not None else None

workspace_pathex = [
    str(repo_root / "packages" / "server"),
    str(repo_root / "packages" / "api"),
    str(repo_root / "packages" / "bff"),
    str(repo_root / "packages" / "mcp_adapter"),
]

a = Analysis(
    [str(policy.entry), str(worker_policy.entry)],
    pathex=workspace_pathex,
    binaries=analysis_binaries(),
    datas=list(policy.datas) + list(worker_policy.datas),
    hiddenimports=list(dict.fromkeys((*policy.hiddenimports, *worker_policy.hiddenimports))),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(policy.excludes),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

host_scripts = pyinstaller_scripts_without(a.scripts, worker_policy.entry.name)
worker_scripts = pyinstaller_scripts_without(a.scripts, policy.entry.name)

exe = EXE(
    pyz,
    host_scripts,
    [],
    exclude_binaries=True,
    name=policy.name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)
worker_exe = EXE(
    pyz,
    worker_scripts,
    [],
    exclude_binaries=True,
    name=worker_policy.name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    worker_exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=policy.name,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{policy.display_name}.app",
        icon=icon,
        bundle_identifier=policy.bundle_identifier,
        info_plist=macos_info_plist(policy),
    )
