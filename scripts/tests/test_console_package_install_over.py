"""Install-over: installer sources must not delete the console data directory."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# ADR 0028 / 0029: OS per-user data dir is not {app} and is not uninstall-deleted.
_DATA_DIR_FRAGMENTS = (
    r"{localappdata}\Planets Console",
    r"{localappdata}\\Planets Console",
    r"{userappdata}\Planets Console",
    "Library/Application Support/Planets Console",
    "~/Library/Application Support/Planets Console",
)

_CHECKED_SECTIONS = ("Files", "Dirs", "InstallDelete", "UninstallDelete")


def _installer_sources() -> list[Path]:
    return sorted({*REPO_ROOT.rglob("*.iss"), *REPO_ROOT.rglob("*.iss.in")})


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
    for path in _installer_sources():
        text = path.read_text(encoding="utf-8")
        for section_name in _CHECKED_SECTIONS:
            body = _section_body(text, section_name)
            if not body.strip():
                continue
            lowered = body.lower()
            for fragment in _DATA_DIR_FRAGMENTS:
                assert fragment.lower() not in lowered, (
                    f"{path} [{section_name}] must not mention {fragment!r}"
                )
