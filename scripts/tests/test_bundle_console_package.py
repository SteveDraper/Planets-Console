"""Console package bundler collect policy (runtime-only tree)."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import bundle_console_package as bundler
import pytest
from bundle_console_package import (
    BUNDLE_NAME,
    analysis_binaries,
    assert_collect_policy_runtime_only,
    collect_policy,
    macos_info_plist,
    write_placeholder_ico,
    write_placeholder_png,
)
from server.package_identity import VERSION_SIDECAR_NAME, version_from_pyproject

from tests.console_package_install_over_helpers import (
    assert_text_excludes_console_data_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_SPEC_PATH = Path(__file__).resolve().parents[1] / "console_package.spec"


def test_version_from_pyproject_is_full_semver_not_short():
    version = version_from_pyproject(REPO_ROOT)
    assert version != "0.1"
    assert version.count(".") >= 2


def test_collect_policy_ships_spa_analytics_and_version_sidecar():
    policy = collect_policy(REPO_ROOT)
    dests = {dest for _src, dest in policy.datas}
    assert dests == {"packages/frontend/dist", "assets/analytics", VERSION_SIDECAR_NAME}
    sources = [Path(src) for src, _dest in policy.datas]
    assert any(src.as_posix().endswith("packages/frontend/dist") for src in sources)
    assert any(src.as_posix().endswith("assets/analytics") for src in sources)
    sidecar = next(Path(src) for src, dest in policy.datas if dest == VERSION_SIDECAR_NAME)
    assert sidecar.is_file()
    assert sidecar.read_text(encoding="utf-8").strip() == version_from_pyproject(REPO_ROOT)
    assert_collect_policy_runtime_only(policy)
    assert "pytest" in policy.excludes
    assert policy.entry.name == "process_host_entry.py"
    assert policy.name == BUNDLE_NAME == "Planets Console"
    assert policy.version == version_from_pyproject(REPO_ROOT)


def test_collect_policy_does_not_add_tests_scripts_docs_or_frontend_src():
    policy = collect_policy(REPO_ROOT)
    blob = " ".join(f"{src} {dest}" for src, dest in policy.datas)
    assert "packages/api/tests" not in blob
    assert "/scripts/" not in blob.replace(str(REPO_ROOT), "")
    assert "/docs/" not in blob
    assert "node_modules" not in blob
    assert "packages/frontend/src" not in blob
    joined_dest = " ".join(dest for _src, dest in policy.datas)
    assert "tests" not in joined_dest


def _spec_call_keyword(tree: ast.AST, func_name: str, keyword: str) -> str | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == func_name
        ):
            for kw in node.keywords:
                if kw.arg == keyword:
                    return ast.unparse(kw.value)
    return None


def test_collect_policy_and_spec_do_not_place_console_data_directory_in_bundle():
    """Install-over: freeze datas/dests and spec layout are not the OS data dir.

    macOS Finder replace of ``{display_name}.app`` and Windows onedir COLLECT
    must not collect ``Library/Application Support/{name}`` or
    ``%LOCALAPPDATA%\\{name}`` into the app tree.
    """
    policy = collect_policy(REPO_ROOT)
    for source, dest in policy.datas:
        assert_text_excludes_console_data_directory(
            f"{source}::{dest}",
            where=f"collect policy datas {source!r} -> {dest!r}",
        )
    spec_text = _SPEC_PATH.read_text(encoding="utf-8")
    assert_text_excludes_console_data_directory(spec_text, where="console_package.spec")
    tree = ast.parse(spec_text)
    assert _spec_call_keyword(tree, "Analysis", "datas") == "list(policy.datas)"
    assert _spec_call_keyword(tree, "COLLECT", "name") == "policy.name"
    bundle_name = _spec_call_keyword(tree, "BUNDLE", "name")
    assert bundle_name in (
        'f"{policy.display_name}.app"',
        "f'{policy.display_name}.app'",
    )


def test_spec_import_surface_exists():
    """console_package.spec must import names that exist on bundle_console_package."""
    tree = ast.parse(_SPEC_PATH.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "bundle_console_package":
            imported.extend(alias.name for alias in node.names)
    assert "analysis_binaries" in imported
    for name in imported:
        assert hasattr(bundler, name), f"spec imports {name!r} but it is missing"
    assert callable(analysis_binaries)


def test_macos_plist_identity_and_full_version():
    policy = collect_policy(REPO_ROOT)
    plist = macos_info_plist(policy)
    assert plist["CFBundleIdentifier"] == "com.github.stevedraper.planets-console"
    assert plist["CFBundleName"] == "Planets Console"
    assert plist["CFBundleDisplayName"] == "Planets Console"
    assert plist["CFBundleShortVersionString"] == version_from_pyproject(REPO_ROOT)
    assert plist["CFBundleVersion"] == version_from_pyproject(REPO_ROOT)
    assert plist["LSBackgroundOnly"] is False
    assert plist["NSSupportsSuddenTermination"] is False


def test_assert_collect_policy_rejects_tests_datas(tmp_path):
    policy = collect_policy(REPO_ROOT)
    tainted = replace(
        policy,
        datas=(*policy.datas, (str(tmp_path / "packages" / "api" / "tests"), "tests")),
    )
    with pytest.raises(ValueError, match="tests"):
        assert_collect_policy_runtime_only(tainted)


def test_placeholder_png_and_ico_round_trip(tmp_path):
    png = tmp_path / "icon.png"
    write_placeholder_png(png, size=16)
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    ico = tmp_path / "icon.ico"
    write_placeholder_ico(ico, size=16)
    assert ico.read_bytes()[:4] == b"\x00\x00\x01\x00"
