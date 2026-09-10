"""Installer wrappers and GitHub Release metadata for the console package."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import wrap_console_package as wrap
from bundle_console_package import BUNDLE_NAME, DIST_DIR_RELATIVE
from server.package_identity import (
    CONSOLE_PACKAGE_DISPLAY_NAME,
    INNO_APP_ID,
    version_from_pyproject,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_ISS_PATH = REPO_ROOT / "scripts" / "console_package.iss"
_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "console-package-release.yml"


def test_release_asset_names_and_title_follow_adr():
    version = "0.1.0"
    assert wrap.macos_dmg_asset_name(version) == "Planets-Console-0.1.0-macos-arm64.dmg"
    assert wrap.windows_setup_asset_name(version) == "Planets-Console-0.1.0-windows-x64-setup.exe"
    assert wrap.release_title(version) == "Planets Console 0.1.0"
    assert wrap.release_tag(version) == "v0.1.0"
    assert wrap.DMG_VOLUME_NAME == CONSOLE_PACKAGE_DISPLAY_NAME == "Planets Console"


def test_release_metadata_uses_pyproject_version():
    version = version_from_pyproject(REPO_ROOT)
    meta = wrap.release_metadata(version)
    assert meta["version"] == version
    assert meta["release_tag"] == f"v{version}"
    assert meta["release_title"] == f"Planets Console {version}"
    assert meta["macos_dmg_asset"] == f"Planets-Console-{version}-macos-arm64.dmg"
    assert meta["windows_setup_asset"] == f"Planets-Console-{version}-windows-x64-setup.exe"


def test_require_tag_matches_version_accepts_v_prefix_and_full_ref():
    wrap.require_tag_matches_version("v1.2.3", "1.2.3")
    wrap.require_tag_matches_version("refs/tags/v1.2.3", "1.2.3")
    with pytest.raises(ValueError, match="v1.2.3"):
        wrap.require_tag_matches_version("v1.2.3-rc1", "1.2.3")
    with pytest.raises(ValueError, match="v0.1.0"):
        wrap.require_tag_matches_version("v0.2.0", "0.1.0")


def test_emit_github_output_appends_key_value_lines(tmp_path):
    path = tmp_path / "github_output"
    path.write_text("preexisting=1\n", encoding="utf-8")
    wrap.emit_github_output(path, {"version": "0.1.0", "release_title": "Planets Console 0.1.0"})
    text = path.read_text(encoding="utf-8")
    assert text.startswith("preexisting=1\n")
    assert "version=0.1.0\n" in text
    assert "release_title=Planets Console 0.1.0\n" in text


def test_main_check_tag_matches_pyproject():
    version = version_from_pyproject(REPO_ROOT)
    assert wrap.main(["--repo-root", str(REPO_ROOT), "--check-tag", f"v{version}"]) == 0


def test_main_check_tag_mismatch_is_nonzero(capsys):
    rc = wrap.main(["--repo-root", str(REPO_ROOT), "--check-tag", "v9.9.9"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "v9.9.9" in err
    assert version_from_pyproject(REPO_ROOT) in err


def test_main_emit_github_output(tmp_path, monkeypatch):
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert wrap.main(["--repo-root", str(REPO_ROOT), "--emit-github-output"]) == 0
    text = output.read_text(encoding="utf-8")
    version = version_from_pyproject(REPO_ROOT)
    assert f"version={version}\n" in text
    assert f"release_tag=v{version}\n" in text
    assert f"release_title=Planets Console {version}\n" in text


def test_main_emit_github_output_requires_env(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert wrap.main(["--repo-root", str(REPO_ROOT), "--emit-github-output"]) == 2


def test_stage_macos_dmg_root_copies_app_and_applications_symlink(tmp_path):
    app = tmp_path / "src" / "Planets Console.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text("plist\n", encoding="utf-8")
    stage = tmp_path / "stage"
    wrap.stage_macos_dmg_root(app, stage)
    staged_app = stage / "Planets Console.app"
    assert (staged_app / "Contents" / "Info.plist").read_text(encoding="utf-8") == "plist\n"
    link = stage / "Applications"
    assert link.is_symlink()
    assert os.readlink(link) == "/Applications"
    wrap.stage_macos_dmg_root(app, stage)
    assert (stage / "Planets Console.app" / "Contents" / "Info.plist").is_file()


def test_hdiutil_create_args_are_udzo_with_planets_console_volume(tmp_path):
    src = tmp_path / "stage"
    dmg = tmp_path / "Planets-Console-0.1.0-macos-arm64.dmg"
    args = wrap.hdiutil_create_args("Planets Console", src, dmg)
    assert args[0] == "hdiutil"
    assert args[1] == "create"
    assert "-volname" in args
    assert args[args.index("-volname") + 1] == "Planets Console"
    assert "-format" in args
    assert args[args.index("-format") + 1] == "UDZO"
    assert "-ov" in args
    assert "-srcfolder" in args
    assert args[args.index("-srcfolder") + 1] == str(src)
    assert args[-1] == str(dmg)


def test_macos_and_windows_bundler_output_paths():
    assert wrap.macos_app_path(REPO_ROOT) == REPO_ROOT / DIST_DIR_RELATIVE / f"{BUNDLE_NAME}.app"
    assert wrap.windows_onedir_path(REPO_ROOT) == REPO_ROOT / DIST_DIR_RELATIVE / BUNDLE_NAME
    exe = wrap.windows_onedir_path(REPO_ROOT) / wrap.WINDOWS_EXE_NAME
    assert exe.name == "Planets Console.exe"


def test_inno_script_is_per_user_start_menu_no_desktop():
    text = _ISS_PATH.read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert r"DefaultDirName={localappdata}\Programs\{#MyAppName}" in text
    assert '#define MyAppName "Planets Console"' in text
    assert f"AppId={{{INNO_APP_ID}" in text
    assert INNO_APP_ID == "{933C1FA0-3D30-4611-AE34-2F7C14C5253B}"
    assert r'Name: "{autoprograms}\{#MyAppName}"' in text
    assert "autodesktop" not in text.lower()
    assert "desktopicon" not in text.lower()
    assert "[UninstallDelete]" not in text
    assert "[Dirs]" not in text
    assert "[Files]" in text
    assert "{app}" in text


def test_iscc_compile_args_pass_defines(tmp_path):
    iscc = tmp_path / "ISCC.exe"
    iss = _ISS_PATH
    source = tmp_path / "Planets Console"
    output = tmp_path / "out"
    args = wrap.iscc_compile_args(
        iscc,
        iss,
        version="0.1.0",
        source_dir=source,
        output_dir=output,
        output_base_filename="Planets-Console-0.1.0-windows-x64-setup",
    )
    assert args[0] == str(iscc)
    assert "/DMyAppVersion=0.1.0" in args
    assert f"/DSourceDir={source}" in args
    assert f"/DOutputDir={output}" in args
    assert "/DOutputBaseFilename=Planets-Console-0.1.0-windows-x64-setup" in args
    assert args[-1] == str(iss)


def test_wrap_console_package_rejects_unsupported_platform():
    with pytest.raises(RuntimeError, match="linux"):
        wrap.wrap_console_package(REPO_ROOT, platform="linux")


def test_release_workflow_pinned_runners_tag_and_dispatch():
    text = _WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "macos-latest" not in text
    assert "windows-latest" not in text
    assert "os: macos-15" in text
    assert "os: windows-2025" in text
    assert "runs-on: ${{ matrix.os }}" in text
    on_start = text.find("\non:\n")
    assert on_start >= 0
    on_rest = text[on_start + 1 :]
    on_end = on_rest.find("\npermissions:")
    if on_end < 0:
        on_end = on_rest.find("\njobs:")
    on_block = on_rest[:on_end]
    assert "workflow_dispatch:" in on_block
    assert '"v*.*.*"' in on_block
    assert "release:" not in on_block
    assert "types: [published]" not in text
    assert 'MACOSX_DEPLOYMENT_TARGET: "11"' in text
    assert "gh release create" in text
    assert "gh release upload" in text
    assert "--clobber" in text
    assert "needs.prepare.outputs.release_title" in text
    assert "--check-tag" in text
    assert (
        "uv run --python 3.14 --no-project python "
        "scripts/wrap_console_package.py --emit-github-output"
    ) in text
    assert "uv run python scripts/bundle_console_package.py" in text
    assert "uv run python scripts/wrap_console_package.py" in text
    assert "npm run build" in text
    assert "if-no-files-found: error" in text
