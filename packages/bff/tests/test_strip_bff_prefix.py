"""Tests for :mod:`bff.strip_bff_prefix` path / raw_path handling."""

from bff.strip_bff_prefix import _raw_path_after_strip_bff


def test_raw_path_strips_literal_bff_prefix_preserves_percent_bytes_in_tail() -> None:
    # ``path`` is decoded; ``raw_path`` can keep % — slice removes only the leading ``/bff`` bytes.
    assert _raw_path_after_strip_bff("/x/y", b"/bff/seg%2Ftail%2Fend") == b"/seg%2Ftail%2Fend"


def test_raw_path_exact_bff_only() -> None:
    assert _raw_path_after_strip_bff("/", b"/bff") == b"/"


def test_raw_path_none_uses_utf8() -> None:
    assert _raw_path_after_strip_bff("/café", None) == "/café".encode("utf-8")


def test_raw_path_non_prefix_falls_back_to_utf8() -> None:
    assert _raw_path_after_strip_bff("/other", b"/not-bff/x") == "/other".encode("utf-8")
