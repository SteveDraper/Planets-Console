"""Installer wrappers for the v1 console package (Mac DMG, Windows Inno).

Turns bundler onedir / ``.app`` output into GitHub Release downloads. Does not
own the console data directory.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
_SERVER_SRC = REPO_ROOT / "packages" / "server"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from server.package_identity import (  # noqa: E402
    CONSOLE_PACKAGE_DISPLAY_NAME,
    INNO_APP_ID,
    version_from_pyproject,
)

ISS_RELATIVE = Path("scripts") / "console_package.iss"
INSTALLER_OUTPUT_RELATIVE = Path("dist") / "console-package-installers"
ASSET_NAME_PREFIX = "Planets-Console"


def _bundle_layout() -> tuple[str, Path, Path]:
    from bundle_console_package import BUNDLE_NAME, DIST_DIR_RELATIVE, WORK_DIR_RELATIVE

    return BUNDLE_NAME, DIST_DIR_RELATIVE, WORK_DIR_RELATIVE


def release_tag(version: str) -> str:
    return f"v{version}"


def release_title(version: str) -> str:
    return f"{CONSOLE_PACKAGE_DISPLAY_NAME} {version}"


def macos_dmg_asset_name(version: str) -> str:
    return f"{ASSET_NAME_PREFIX}-{version}-macos-arm64.dmg"


def windows_setup_asset_name(version: str) -> str:
    return f"{ASSET_NAME_PREFIX}-{version}-windows-x64-setup.exe"


def normalize_tag_name(tag: str) -> str:
    prefix = "refs/tags/"
    if tag.startswith(prefix):
        return tag[len(prefix) :]
    return tag


def require_tag_matches_version(tag: str, version: str) -> None:
    """Refuse a git tag that is not ``v`` plus the root pyproject version."""
    actual = normalize_tag_name(tag)
    expected = release_tag(version)
    if actual != expected:
        raise ValueError(
            f"git tag {actual!r} must equal {expected!r} (root pyproject version {version})"
        )


def release_metadata(version: str) -> dict[str, str]:
    return {
        "version": version,
        "release_tag": release_tag(version),
        "release_title": release_title(version),
        "macos_dmg_asset": macos_dmg_asset_name(version),
        "windows_setup_asset": windows_setup_asset_name(version),
    }


def emit_github_output(path: Path, values: Mapping[str, str]) -> None:
    lines = "".join(f"{key}={value}\n" for key, value in values.items())
    with path.open("a", encoding="utf-8") as handle:
        handle.write(lines)


def macos_app_path(repo_root: Path) -> Path:
    bundle_name, dist_dir, _work = _bundle_layout()
    return repo_root / dist_dir / f"{bundle_name}.app"


def windows_onedir_path(repo_root: Path) -> Path:
    bundle_name, dist_dir, _work = _bundle_layout()
    return repo_root / dist_dir / bundle_name


def installer_output_dir(repo_root: Path) -> Path:
    return repo_root / INSTALLER_OUTPUT_RELATIVE


def iss_path(repo_root: Path) -> Path:
    return repo_root / ISS_RELATIVE


def stage_macos_dmg_root(app_path: Path, stage_dir: Path) -> None:
    """Copy the ``.app`` and add an Applications symlink (hdiutil srcfolder)."""
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)
    dest_app = stage_dir / app_path.name
    shutil.copytree(app_path, dest_app, symlinks=True)
    os.symlink("/Applications", stage_dir / "Applications")


def hdiutil_create_args(
    volume_name: str,
    src_folder: Path,
    output_dmg: Path,
    *,
    executable: str | Path = "hdiutil",
) -> list[str]:
    return [
        str(executable),
        "create",
        "-volname",
        volume_name,
        "-srcfolder",
        str(src_folder),
        "-ov",
        "-format",
        "UDZO",
        str(output_dmg),
    ]


def find_hdiutil() -> Path:
    found = shutil.which("hdiutil")
    if found:
        return Path(found)
    raise FileNotFoundError("hdiutil is required to wrap the macOS console package")


def wrap_macos_dmg(repo_root: Path) -> Path:
    app = macos_app_path(repo_root)
    if not app.is_dir():
        raise FileNotFoundError(
            f"bundler .app is missing at {app}; run: make bundle_console_package"
        )
    version = version_from_pyproject(repo_root)
    output_dir = installer_output_dir(repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dmg = output_dir / macos_dmg_asset_name(version)
    _, _, work_dir = _bundle_layout()
    stage = repo_root / work_dir / "dmg-stage"
    stage_macos_dmg_root(app, stage)
    subprocess.run(
        hdiutil_create_args(
            CONSOLE_PACKAGE_DISPLAY_NAME,
            stage,
            output_dmg,
            executable=find_hdiutil(),
        ),
        check=True,
        cwd=repo_root,
    )
    if not output_dmg.is_file():
        raise FileNotFoundError(f"hdiutil did not write {output_dmg}")
    return output_dmg


def find_iscc() -> Path:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return Path(found)
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    for candidate in (
        Path(program_files_x86) / "Inno Setup 6" / "ISCC.exe",
        Path(program_files) / "Inno Setup 6" / "ISCC.exe",
    ):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("Inno Setup ISCC.exe is required to wrap the Windows console package")


def _windows_exe_name() -> str:
    bundle_name, _, _ = _bundle_layout()
    return f"{bundle_name}.exe"


def _inno_app_id_compiler_value(app_id: str) -> str:
    """Inno Setup treats `{` as the start of a constant; AppId uses a doubled brace."""
    if not app_id.startswith("{") or not app_id.endswith("}"):
        raise ValueError(f"Inno AppId must be a braced GUID, got {app_id!r}")
    return "{" + app_id


def iscc_compile_args(
    iscc: Path,
    iss: Path,
    *,
    version: str,
    source_dir: Path,
    output_dir: Path,
    output_base_filename: str,
) -> list[str]:
    return [
        str(iscc),
        f"/DMyAppVersion={version}",
        f"/DMyAppName={CONSOLE_PACKAGE_DISPLAY_NAME}",
        f"/DMyAppExeName={_windows_exe_name()}",
        f"/DMyAppId={_inno_app_id_compiler_value(INNO_APP_ID)}",
        f"/DSourceDir={source_dir}",
        f"/DOutputDir={output_dir}",
        f"/DOutputBaseFilename={output_base_filename}",
        str(iss),
    ]


def wrap_windows_setup(repo_root: Path) -> Path:
    onedir = windows_onedir_path(repo_root)
    exe = onedir / _windows_exe_name()
    if not exe.is_file():
        raise FileNotFoundError(
            f"bundler onedir exe is missing at {exe}; run: make bundle_console_package"
        )
    iss = iss_path(repo_root)
    if not iss.is_file():
        raise FileNotFoundError(f"Inno script is missing: {iss}")
    version = version_from_pyproject(repo_root)
    output_dir = installer_output_dir(repo_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_base = windows_setup_asset_name(version).removesuffix(".exe")
    subprocess.run(
        iscc_compile_args(
            find_iscc(),
            iss,
            version=version,
            source_dir=onedir,
            output_dir=output_dir,
            output_base_filename=output_base,
        ),
        check=True,
        cwd=repo_root,
    )
    output_exe = output_dir / windows_setup_asset_name(version)
    if not output_exe.is_file():
        raise FileNotFoundError(f"ISCC did not write {output_exe}")
    return output_exe


def wrap_console_package(repo_root: Path, *, platform: str | None = None) -> Path:
    plat = platform if platform is not None else sys.platform
    if plat == "darwin":
        return wrap_macos_dmg(repo_root)
    if plat == "win32":
        return wrap_windows_setup(repo_root)
    raise RuntimeError(f"installer wrapper does not support platform {plat!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wrap the v1 console package into a GitHub Release .dmg or setup .exe."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Workspace root (default: parent of scripts/).",
    )
    parser.add_argument(
        "--check-tag",
        metavar="TAG",
        help="Exit 1 unless TAG equals v + root pyproject version.",
    )
    parser.add_argument(
        "--emit-github-output",
        action="store_true",
        help="Append release metadata to $GITHUB_OUTPUT and exit.",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    version = version_from_pyproject(repo_root)
    if args.check_tag is not None:
        try:
            require_tag_matches_version(args.check_tag, version)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 1
        return 0
    if args.emit_github_output:
        output_path = os.environ.get("GITHUB_OUTPUT")
        if not output_path:
            print("GITHUB_OUTPUT is not set", file=sys.stderr)
            return 2
        emit_github_output(Path(output_path), release_metadata(version))
        return 0
    try:
        wrapped = wrap_console_package(repo_root)
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(wrapped)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
