"""Install-over: installer wrappers must not delete the console data directory.

Freeze-tree coverage (collect policy datas/dests and ``console_package.spec``)
lives in ``test_bundle_console_package.py``. This module scans the Inno
wrapper source only -- not a repo-wide glob.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.console_package_install_over_helpers import (
    assert_text_excludes_console_data_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Inno wrapper source next to console_package.spec (ADR 0028).
_ISS_PATH = REPO_ROOT / "scripts" / "console_package.iss"

_CHECKED_SECTIONS = ("Files", "Dirs", "InstallDelete", "UninstallDelete")

_WRAPPER_MISSING_REASON = (
    "Inno installer wrapper source is required at scripts/console_package.iss. "
    "See ADR 0028 and "
    "https://github.com/SteveDraper/Planets-Console/issues/433."
)


def _section_body(text: str, name: str) -> str:
    marker = f"[{name}]"
    start = text.lower().find(marker.lower())
    if start < 0:
        return ""
    rest = text[start + len(marker) :]
    next_section = rest.find("\n[")
    return rest if next_section < 0 else rest[:next_section]


def test_inno_files_and_uninstall_do_not_include_console_data_directory():
    """Inno [Files] / uninstall-delete must not mention the console data directory."""
    if not _ISS_PATH.is_file():
        pytest.fail(_WRAPPER_MISSING_REASON)
    text = _ISS_PATH.read_text(encoding="utf-8")
    rel = _ISS_PATH.relative_to(REPO_ROOT).as_posix()
    saw_section = False
    for section_name in _CHECKED_SECTIONS:
        body = _section_body(text, section_name)
        if not body.strip():
            continue
        saw_section = True
        assert_text_excludes_console_data_directory(body, where=f"{rel} [{section_name}]")
    assert saw_section, f"{rel} must contain at least one of {_CHECKED_SECTIONS}"
