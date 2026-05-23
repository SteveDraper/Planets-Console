"""Unit tests for breakpoint registry helpers."""

from pathlib import Path

import pytest
from api.errors import ValidationError
from api.storage.boundaries import (
    document_relpath,
    is_navigable_prefix,
    is_registered_path,
    resolve_breakpoint,
)


def test_resolve_breakpoint_game_info():
    bp, suffix = resolve_breakpoint("games/628580/info")
    assert bp == "games/628580/info"
    assert suffix is None


def test_resolve_breakpoint_nested_in_document():
    bp, suffix = resolve_breakpoint("games/628580/info/settings")
    assert bp == "games/628580/info"
    assert suffix == "settings"


def test_resolve_breakpoint_turn():
    bp, suffix = resolve_breakpoint("games/628580/1/turns/111")
    assert bp == "games/628580/1/turns/111"
    assert suffix is None


def test_resolve_breakpoint_credentials():
    bp, suffix = resolve_breakpoint("credentials/accounts/alice/api_key")
    assert bp == "credentials/accounts/alice"
    assert suffix == "api_key"


def test_resolve_breakpoint_unregistered_raises():
    with pytest.raises(ValidationError, match="Unregistered"):
        resolve_breakpoint("unknown/path")


def test_document_relpath():
    assert document_relpath("games/628580/info") == Path("games/628580/info.json")


def test_is_navigable_prefix():
    assert is_navigable_prefix("")
    assert is_navigable_prefix("games")
    assert is_navigable_prefix("games/628580")
    assert not is_navigable_prefix("unknown")


def test_is_registered_path():
    assert is_registered_path("games/628580/info")
    assert not is_registered_path("games/628580")


@pytest.mark.parametrize(
    "path",
    [
        "games/../info",
        "games/628580/../info",
        "games/foo/../../credentials/accounts/alice",
        "games/628580/1/turns/111/../../../info",
        "games\\628580\\info",
        "games//628580/info",
        "games/./info",
    ],
)
def test_resolve_breakpoint_rejects_unsafe_segments(path: str):
    with pytest.raises(ValidationError):
        resolve_breakpoint(path)


@pytest.mark.parametrize(
    "path",
    [
        "games/..",
        "games/../info",
        "games\\628580",
        "games//628580",
    ],
)
def test_is_navigable_prefix_rejects_unsafe_segments(path: str):
    with pytest.raises(ValidationError):
        is_navigable_prefix(path)


def test_is_registered_path_rejects_unsafe_segments():
    assert not is_registered_path("games/../info")
