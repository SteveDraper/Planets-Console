"""Tests for :mod:`check_no_monolithic_schema`."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from check_no_monolithic_schema import main


def test_passes_when_monolithic_schema_absent(tmp_path: Path) -> None:
    missing = tmp_path / "schema.ts"
    with mock.patch(
        "check_no_monolithic_schema.MONOLITHIC_SCHEMA",
        missing,
    ):
        assert main() == 0


def test_fails_when_monolithic_schema_present(tmp_path: Path) -> None:
    present = tmp_path / "schema.ts"
    present.write_text("// monolithic schema must not return\n", encoding="utf-8")
    with mock.patch(
        "check_no_monolithic_schema.MONOLITHIC_SCHEMA",
        present,
    ):
        assert main() == 1
