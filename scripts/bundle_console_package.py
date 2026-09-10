"""PyInstaller collect policy and bundler for the v1 console package.

Freeze from the process host entry import graph. Bundled datas are the prebuilt
SPA and runtime ``assets/analytics`` only -- not the git tree, tests, or scripts.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import tomllib
import zlib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_SERVER_SRC = REPO_ROOT / "packages" / "server"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

ENTRY_RELATIVE = Path("packages") / "server" / "server" / "process_host_entry.py"
SPA_DIST_RELATIVE = Path("packages") / "frontend" / "dist"
ANALYTICS_ASSETS_RELATIVE = Path("assets") / "analytics"
BUNDLE_NAME = "Planets Console"
DIST_DIR_RELATIVE = Path("dist") / "console-package"
WORK_DIR_RELATIVE = Path("build") / "console-package"

# Uvicorn factory / protocol loaders are string-imported. OR-Tools SAT is lazy
# relative to the process host module graph.
HIDDENIMPORTS = (
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.http.httptools_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "ortools.sat.python.cp_model",
)

# Do not collect_all() in a way that pulls tests. Exclude pytest explicitly.
EXCLUDES = (
    "pytest",
    "_pytest",
    "py.test",
)

FORBIDDEN_BUNDLE_SUBSTRINGS = (
    "/tests/",
    "\\tests\\",
    "/scripts/",
    "\\scripts\\",
    "/docs/",
    "\\docs\\",
    "/node_modules/",
    "\\node_modules\\",
    "/packages/frontend/src/",
    "\\packages\\frontend\\src\\",
)


@dataclass(frozen=True)
class CollectPolicy:
    """Datas and analysis flags for the console package bundler."""

    entry: Path
    datas: tuple[tuple[str, str], ...]
    hiddenimports: tuple[str, ...]
    excludes: tuple[str, ...]
    name: str
    bundle_identifier: str
    display_name: str
    version: str
    app_user_model_id: str


def version_from_pyproject(repo_root: Path = REPO_ROOT) -> str:
    """Read ``[project].version`` from the workspace root pyproject.toml."""
    payload = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    version = payload["project"]["version"]
    if not isinstance(version, str) or not version:
        raise ValueError("root pyproject.toml is missing [project].version")
    return version


def collect_policy(repo_root: Path = REPO_ROOT) -> CollectPolicy:
    """Return the runtime-only collect policy. Does not import PyInstaller."""
    from server.package_identity import (
        APP_USER_MODEL_ID,
        CFBUNDLE_IDENTIFIER,
        CONSOLE_PACKAGE_DISPLAY_NAME,
    )

    spa = repo_root / SPA_DIST_RELATIVE
    assets = repo_root / ANALYTICS_ASSETS_RELATIVE
    entry = repo_root / ENTRY_RELATIVE
    datas = (
        (str(spa), str(SPA_DIST_RELATIVE).replace("\\", "/")),
        (str(assets), str(ANALYTICS_ASSETS_RELATIVE).replace("\\", "/")),
    )
    return CollectPolicy(
        entry=entry,
        datas=datas,
        hiddenimports=HIDDENIMPORTS,
        excludes=EXCLUDES,
        name=CONSOLE_PACKAGE_DISPLAY_NAME,
        bundle_identifier=CFBUNDLE_IDENTIFIER,
        display_name=CONSOLE_PACKAGE_DISPLAY_NAME,
        version=version_from_pyproject(repo_root),
        app_user_model_id=APP_USER_MODEL_ID,
    )


def assert_collect_policy_runtime_only(policy: CollectPolicy) -> None:
    """Reject datas that would ship tests, docs, scripts, or frontend sources."""
    for source, dest in policy.datas:
        combined = f"{source}::{dest}"
        for fragment in FORBIDDEN_BUNDLE_SUBSTRINGS:
            if fragment in combined:
                raise ValueError(f"collect policy must not ship {fragment!r}; got {combined!r}")
        dest_norm = dest.replace("\\", "/")
        if dest_norm.endswith("tests") or "/tests/" in f"/{dest_norm}/":
            raise ValueError(f"collect policy must not dest-copy tests: {dest!r}")
    if "pytest" not in policy.excludes:
        raise ValueError("collect policy must exclude pytest")


def macos_info_plist(policy: CollectPolicy) -> dict[str, object]:
    """Info.plist keys for the windowed ``.app`` (version is full pyproject, not ``0.1``)."""
    return {
        "CFBundleName": policy.display_name,
        "CFBundleDisplayName": policy.display_name,
        "CFBundleIdentifier": policy.bundle_identifier,
        "CFBundleShortVersionString": policy.version,
        "CFBundleVersion": policy.version,
        "CFBundleGetInfoString": f"{policy.display_name} {policy.version}",
        "NSHighResolutionCapable": True,
        "NSSupportsSuddenTermination": False,
        "LSBackgroundOnly": False,
    }
    """Native libs PyInstaller will not infer from Python imports alone."""
    from PyInstaller.utils.hooks import collect_dynamic_libs

    binaries: list = []
    binaries += collect_dynamic_libs("ortools")
    binaries += collect_dynamic_libs("numpy")
    return binaries


def write_placeholder_png(path: Path, size: int = 256) -> None:
    """Write a flat fog-gray square PNG (icon art stays map fog)."""
    # Fog gray close to the SPA chrome.
    pixel = bytes((64, 69, 74, 255))
    rgba = pixel * (size * size)
    raw = b""
    stride = size * 4
    for row in range(size):
        raw += b"\x00" + rgba[row * stride : (row + 1) * stride]
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def write_placeholder_ico(path: Path, size: int = 32) -> None:
    png_path = path.with_suffix(".png")
    write_placeholder_png(png_path, size=size)
    png = png_path.read_bytes()
    header = struct.pack("<HHH", 0, 1, 1)
    width = size if size < 256 else 0
    entry = struct.pack("<BBBBHHII", width, width, 0, 0, 1, 32, len(png), 6 + 16)
    path.write_bytes(header + entry + png)


def write_placeholder_icns(path: Path, work_dir: Path) -> Path | None:
    """Build a macOS .icns via iconutil. Returns None when iconutil is unavailable."""
    iconset = work_dir / "Planets Console.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for pixel_size, name in (
        (16, "icon_16x16.png"),
        (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"),
        (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"),
        (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"),
        (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"),
        (1024, "icon_512x512@2x.png"),
    ):
        write_placeholder_png(iconset / name, size=pixel_size)
    try:
        subprocess.run(
            ["iconutil", "-c", "icns", "-o", str(path), str(iconset)],
            check=True,
            capture_output=True,
        )
    except OSError, subprocess.CalledProcessError:
        return None
    return path if path.is_file() else None


def prepare_placeholder_icon(work_dir: Path) -> Path | None:
    if sys.platform == "darwin":
        icns = work_dir / "planets-console.icns"
        return write_placeholder_icns(icns, work_dir)
    ico = work_dir / "planets-console.ico"
    write_placeholder_ico(ico)
    return ico


def pyinstaller_args(repo_root: Path) -> list[str]:
    """CLI args for ``PyInstaller.__main__.run`` using the committed spec."""
    spec = Path(__file__).resolve().parent / "console_package.spec"
    dist = repo_root / DIST_DIR_RELATIVE
    work = repo_root / WORK_DIR_RELATIVE
    return [
        "--noconfirm",
        "--clean",
        f"--distpath={dist}",
        f"--workpath={work}",
        str(spec),
    ]


def validate_inputs(repo_root: Path, policy: CollectPolicy) -> None:
    assert_collect_policy_runtime_only(policy)
    if not policy.entry.is_file():
        raise FileNotFoundError(f"process host entry is missing: {policy.entry}")
    spa = repo_root / SPA_DIST_RELATIVE
    if not spa.is_dir() or not (spa / "index.html").is_file():
        raise FileNotFoundError(
            f"prebuilt SPA is missing at {spa}; run: cd packages/frontend && npm run build"
        )
    assets = repo_root / ANALYTICS_ASSETS_RELATIVE
    if not assets.is_dir():
        raise FileNotFoundError(f"analytics assets are missing: {assets}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bundle the v1 console package with PyInstaller onedir --windowed."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Workspace root (default: parent of scripts/).",
    )
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    policy = collect_policy(repo_root)
    validate_inputs(repo_root, policy)
    try:
        import PyInstaller.__main__
    except ImportError:
        print(
            "PyInstaller is required: uv sync --extra package",
            file=sys.stderr,
        )
        return 2
    PyInstaller.__main__.run(pyinstaller_args(repo_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
