"""Ephemeral backend tests: deep-copy isolation and asset initialization."""

import pytest
from api.errors import NotFoundError, ValidationError
from api.storage.memory_asset import MemoryAssetBackend

INFO = "games/sample/info"
NESTED = f"{INFO}/nested"


@pytest.fixture
def backend():
    return MemoryAssetBackend(
        initial={
            "games": {
                "sample": {
                    "info": {
                        "turn": 2,
                        "nested": {
                            "earth": {"name": "Earth", "moons": ["Luna"]},
                            "mars": {"name": "Mars", "moons": ["Phobos", "Deimos"]},
                        },
                    }
                }
            }
        }
    )


def test_get_returns_deep_copy(backend):
    data = backend.get(INFO)
    assert data["turn"] == 2
    data["turn"] = 999
    assert backend.get(INFO)["turn"] == 2


def test_get_root_raises(backend):
    with pytest.raises(ValidationError, match="Cannot get root"):
        backend.get("")


def test_put_root_raises(backend):
    with pytest.raises(ValidationError, match="Cannot put root"):
        backend.put("", {"x": 1})


def test_delete_root_raises(backend):
    with pytest.raises(ValidationError, match="Cannot delete root"):
        backend.delete("")


def test_empty_initial_accepts_registered_put():
    backend = MemoryAssetBackend(initial={})
    backend.put(f"{INFO}/turn", 1)
    assert backend.get(f"{INFO}/turn") == 1


def test_get_missing_raises(backend):
    with pytest.raises(NotFoundError):
        backend.get("games/missing/info")


def test_list_root(backend):
    assert backend.list("") == ["games"]
