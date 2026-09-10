"""Install-over fragments for freeze-tree and Inno wrapper tests (ADR 0029)."""

from __future__ import annotations

from server.package_identity import CONSOLE_PACKAGE_DISPLAY_NAME


def console_data_directory_fragments() -> tuple[str, ...]:
    """Path fragments that identify the OS console data directory."""
    name = CONSOLE_PACKAGE_DISPLAY_NAME
    return (
        f"Library/Application Support/{name}",
        f"Library\\Application Support\\{name}",
        f"~/Library/Application Support/{name}",
        f"Application Support/{name}",
        f"Application Support\\{name}",
        f"%LOCALAPPDATA%\\{name}",
        f"%LOCALAPPDATA%/{name}",
        f"AppData/Local/{name}",
        f"AppData\\Local\\{name}",
        rf"{{localappdata}}\{name}",
        rf"{{localappdata}}\\{name}",
        rf"{{userappdata}}\{name}",
        rf"{{userappdata}}\\{name}",
    )


def assert_text_excludes_console_data_directory(text: str, *, where: str) -> None:
    """Fail if ``text`` mentions the OS console data directory."""
    fragments = console_data_directory_fragments()
    assert fragments, "console data directory fragments must not be empty"
    lowered = text.lower()
    for fragment in fragments:
        assert CONSOLE_PACKAGE_DISPLAY_NAME in fragment
        assert fragment.lower() not in lowered, (
            f"{where} must not mention the console data directory fragment {fragment!r}"
        )
