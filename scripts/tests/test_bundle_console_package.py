"""Console package bundler collect policy (runtime-only tree)."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import bundle_console_package as bundler
import pytest
from bundle_console_package import (
    BUNDLE_NAME,
    MACOSX_DEPLOYMENT_TARGET,
    analysis_binaries,
    assert_collect_policy_runtime_only,
    collect_policy,
    ensure_macos_deployment_target,
    macos_info_plist,
    pyinstaller_scripts_without,
    sat_worker_collect_policy,
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


def _pyinstaller_datas_relpath(source: str, dest_dir: str) -> str:
    """Relative path PyInstaller writes under ``sys._MEIPASS`` for a file datas entry.

    Analysis ``datas`` dest is a directory. Dest equal to the filename nests the file.
    """
    name = Path(source).name
    if dest_dir in (".", "./"):
        return name
    return f"{dest_dir.replace('\\', '/').rstrip('/')}/{name}"


def test_version_sidecar_lands_at_meipass_filename_not_nested_folder():
    policy = collect_policy(REPO_ROOT)
    matches = [(src, dest) for src, dest in policy.datas if Path(src).name == VERSION_SIDECAR_NAME]
    assert len(matches) == 1
    source, dest = matches[0]
    assert Path(source).is_file()
    assert _pyinstaller_datas_relpath(source, dest) == VERSION_SIDECAR_NAME
    assert dest == "."


def test_collect_policy_ships_spa_analytics_and_version_sidecar():
    policy = collect_policy(REPO_ROOT)
    dests = {dest for _src, dest in policy.datas}
    assert dests == {"packages/frontend/dist", "assets/analytics", "."}
    sources = [Path(src) for src, _dest in policy.datas]
    assert any(src.as_posix().endswith("packages/frontend/dist") for src in sources)
    assert any(src.as_posix().endswith("assets/analytics") for src in sources)
    sidecar = next(
        Path(src) for src, dest in policy.datas if Path(src).name == VERSION_SIDECAR_NAME
    )
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
    values = _spec_call_keywords(tree, func_name, keyword)
    return values[0] if values else None


def _spec_call_keywords(tree: ast.AST, func_name: str, keyword: str) -> list[str]:
    values: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == func_name
        ):
            for kw in node.keywords:
                if kw.arg == keyword:
                    values.append(ast.unparse(kw.value))
    return values


def _spec_exe_console_by_name(tree: ast.AST) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "EXE"
        ):
            continue
        name = None
        console = None
        for kw in node.keywords:
            if kw.arg == "name":
                name = ast.unparse(kw.value)
            elif kw.arg == "console":
                console = ast.unparse(kw.value)
        if name is not None and console is not None:
            mapping[name] = console
    return mapping


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
    worker_policy = sat_worker_collect_policy(REPO_ROOT)
    assert worker_policy.datas == ()
    assert_collect_policy_runtime_only(worker_policy)
    spec_text = _SPEC_PATH.read_text(encoding="utf-8")
    assert_text_excludes_console_data_directory(spec_text, where="console_package.spec")
    tree = ast.parse(spec_text)
    analysis_datas = _spec_call_keywords(tree, "Analysis", "datas")
    assert analysis_datas == ["list(policy.datas) + list(worker_policy.datas)"]
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
    assert "sat_worker_collect_policy" in imported
    assert "pyinstaller_scripts_without" in imported


def test_sat_worker_collect_policy_is_sibling_entry_without_spa_or_data_dir():
    from api.compute.process_pool_executable import SAT_WORKER_STEM

    worker_policy = sat_worker_collect_policy(REPO_ROOT)
    assert worker_policy.entry.is_file()
    assert worker_policy.entry.name == "sat_worker_entry.py"
    assert worker_policy.name == SAT_WORKER_STEM
    assert worker_policy.datas == ()
    assert_collect_policy_runtime_only(worker_policy)


def test_spec_freezes_sat_worker_console_exe_next_to_process_host():
    tree = ast.parse(_SPEC_PATH.read_text(encoding="utf-8"))
    console_by_name = _spec_exe_console_by_name(tree)
    assert console_by_name["policy.name"] == "False"
    assert console_by_name["worker_policy.name"] == "True"
    collect_call = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "COLLECT"
        ):
            collect_call = node
            break
    assert collect_call is not None
    collect_args = [ast.unparse(arg) for arg in collect_call.args]
    assert collect_args[:2] == ["exe", "worker_exe"]
    analysis_scripts = None
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Analysis"
        ):
            assert node.args
            analysis_scripts = ast.unparse(node.args[0])
            break
    assert analysis_scripts is not None
    assert "policy.entry" in analysis_scripts
    assert "worker_policy.entry" in analysis_scripts


def test_pyinstaller_scripts_without_keeps_bootstrap_and_one_user_entry():
    scripts = [
        ("pyiboot01_bootstrap", "/boot/pyiboot01_bootstrap.py", "PYSOURCE"),
        ("process_host_entry", "/x/process_host_entry.py", "PYSOURCE"),
        ("sat_worker_entry", "/x/sat_worker_entry.py", "PYSOURCE"),
    ]
    host = pyinstaller_scripts_without(scripts, "sat_worker_entry.py")
    worker = pyinstaller_scripts_without(scripts, "process_host_entry.py")
    assert [item[0] for item in host] == ["pyiboot01_bootstrap", "process_host_entry"]
    assert [item[0] for item in worker] == ["pyiboot01_bootstrap", "sat_worker_entry"]
    with pytest.raises(ValueError, match="missing_entry.py"):
        pyinstaller_scripts_without(scripts, "missing_entry.py")


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


def test_ensure_macos_deployment_target_forces_11_on_darwin(monkeypatch):
    monkeypatch.setattr(bundler.sys, "platform", "darwin")
    env: dict[str, str] = {}
    ensure_macos_deployment_target(env)
    assert env["MACOSX_DEPLOYMENT_TARGET"] == MACOSX_DEPLOYMENT_TARGET == "11"
    env["MACOSX_DEPLOYMENT_TARGET"] = "15.0"
    ensure_macos_deployment_target(env)
    assert env["MACOSX_DEPLOYMENT_TARGET"] == "11"


def test_ensure_macos_deployment_target_is_noop_off_darwin(monkeypatch):
    monkeypatch.setattr(bundler.sys, "platform", "win32")
    env: dict[str, str] = {}
    ensure_macos_deployment_target(env)
    assert "MACOSX_DEPLOYMENT_TARGET" not in env
