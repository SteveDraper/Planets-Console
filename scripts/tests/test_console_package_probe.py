"""Pins for the console-package occupancy probe (Makefile, PR CI, Mac workflow)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_MAKEFILE = REPO_ROOT / "Makefile"
_PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "test.yml"
_PROBE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "console-package-probe.yml"
_RELEASE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "console-package-release.yml"
_CONFIG_DOC = REPO_ROOT / "docs" / "configuration.md"


def test_makefile_ci_and_test_do_not_freeze_or_run_probe():
    text = _MAKEFILE.read_text(encoding="utf-8")
    ci_line = next(line for line in text.splitlines() if line.startswith("ci:"))
    test_line = next(line for line in text.splitlines() if line.startswith("test:"))
    assert "bundle_console_package" not in ci_line
    assert "console_package_probe" not in ci_line
    assert "bundle_console_package" not in test_line
    assert "console_package_probe" not in test_line


def test_makefile_documents_uv_and_frozen_probe_commands():
    text = _MAKEFILE.read_text(encoding="utf-8")
    assert "console_package_probe:" in text
    assert "--console-package-probe" in text
    assert "--scores-solve-tree" in text
    assert "SCORES_SOLVE_TREE" in text
    assert "python -m server.process_host" in text
    assert "FROZEN" in text
    assert "bundle_console_package" in text
    assert "Planets Console.app" in text
    assert "open -n -W" in text


def test_pr_ci_stays_ubuntu_make_ci_without_freeze():
    text = _PR_WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: ubuntu-latest" in text
    assert "run: make ci" in text
    assert "bundle_console_package" not in text
    assert "console-package-probe" not in text
    assert "macos-15" not in text


def test_probe_workflow_is_macos_15_and_runs_both_baselines():
    text = _PROBE_WORKFLOW.read_text(encoding="utf-8")
    assert "name: console-package-probe" in text
    on_start = text.find("\non:\n")
    assert on_start >= 0
    on_rest = text[on_start + 1 :]
    on_end = on_rest.find("\npermissions:")
    if on_end < 0:
        on_end = on_rest.find("\njobs:")
    on_block = on_rest[:on_end]
    assert "workflow_dispatch:" in on_block
    assert "pull_request:" not in on_block
    assert "push:" not in on_block
    assert "macos-latest" not in text
    assert "runs-on: macos-15" in text
    assert "--console-package-probe" in text
    assert "python -m server.process_host" in text
    assert "Planets Console.app" in text
    assert "open -n -W" in text
    assert "uv-probe.json" in text
    assert "frozen-probe.json" in text
    assert "actions/upload-artifact@v4" in text
    assert "bundle_console_package.py" in text
    assert "wrap_console_package.py" not in text


def test_release_workflow_does_not_run_occupancy_probe():
    text = _RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "--console-package-probe" not in text
    assert "uv-probe.json" not in text
    assert "frozen-probe.json" not in text


def test_configuration_docs_document_local_probe_command():
    text = _CONFIG_DOC.read_text(encoding="utf-8")
    assert "make console_package_probe" in text
    assert "--console-package-probe" in text
    assert "FROZEN=1" in text
    assert "largeDocument" in text
    assert "775" in text
    assert "observationPersist" in text
    assert "scoresSolve" in text
    assert "SCORES_SOLVE_TREE" in text
    assert "appKitOn" in text
    assert "NSApplication" in text or "AppKit" in text
