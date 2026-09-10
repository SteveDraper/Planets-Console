"""Install-over: installer wrappers must not delete the console data directory.

Freeze-tree coverage (collect policy datas/dests and ``console_package.spec``)
lives in ``test_bundle_console_package.py``. This module scans explicit Inno
wrapper paths only -- not a repo-wide glob.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.console_package_install_over_helpers import (
    assert_text_excludes_console_data_directory,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

# Explicit Inno paths (ADR 0028 / issue 429), next to console_package.spec.
_EXPECTED_INNO_SOURCES = (
    REPO_ROOT / "scripts" / "console_package.iss",
    REPO_ROOT / "scripts" / "console_package.iss.in",
)

_CHECKED_SECTIONS = ("Files", "Dirs", "InstallDelete", "UninstallDelete")

_WRAPPER_SKIP_REASON = (
    "Inno installer wrapper sources are absent at the explicit paths "
    "scripts/console_package.iss and scripts/console_package.iss.in. "
    "See ADR 0028 and https://github.com/SteveDraper/Planets-Console/issues/429. "
    "Freeze-tree install-over is pinned in test_bundle_console_package.py."
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
    present = [path for path in _EXPECTED_INNO_SOURCES if path.is_file()]
    if not present:
        pytest.skip(_WRAPPER_SKIP_REASON)
    saw_section = False
    for path in present:
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(REPO_ROOT).as_posix()
        for section_name in _CHECKED_SECTIONS:
            body = _section_body(text, section_name)
            if not body.strip():
                continue
            saw_section = True
            assert_text_excludes_console_data_directory(body, where=f"{rel} [{section_name}]")
    assert saw_section, (
        f"{', '.join(p.relative_to(REPO_ROOT).as_posix() for p in present)} "
        f"must contain at least one of {_CHECKED_SECTIONS}"
    )
