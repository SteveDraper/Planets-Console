"""Unit tests for MemoryAssetBackend: get/put/delete/list with path semantics."""

import pytest
from api.errors import NotFoundError
from api.storage.memory_asset import MemoryAssetBackend
from api.storage.path_utils import deep_copy_value

INITIAL = {
    "game": {"id": "g1", "turn": 2},
    "planets": {
        "sol": {
            "earth": {"name": "Earth", "moons": ["Luna"]},
            "mars": {"name": "Mars", "moons": ["Phobos", "Deimos"]},
        }
    },
}


@pytest.fixture
def backend():
    """Backend initialized from a copy of INITIAL so tests can mutate."""
    return MemoryAssetBackend(initial=deep_copy_value(INITIAL))


def test_get_root(backend):
    data = backend.get("")
    assert data == INITIAL
    assert data is not INITIAL  # deep copy
    data["game"]["turn"] = 999
    assert backend.get("")["game"]["turn"] == 2


def test_get_nested(backend):
    assert backend.get("game") == {"id": "g1", "turn": 2}
    assert backend.get("game/turn") == 2
    assert backend.get("planets/sol/earth/name") == "Earth"
    assert backend.get("planets/sol/mars/moons") == ["Phobos", "Deimos"]


def test_get_array_index(backend):
    assert backend.get("planets/sol/earth/moons/@0") == "Luna"
    assert backend.get("planets/sol/mars/moons/@-1") == "Deimos"


def test_get_missing_raises(backend):
    with pytest.raises(NotFoundError, match="Path does not exist"):
        backend.get("missing")
    with pytest.raises(NotFoundError):
        backend.get("game/unknown")


def test_put_creates_object_ancestors(backend):
    backend.put("new/nested/key", {"value": 42})
    assert backend.get("new") == {"nested": {"key": {"value": 42}}}


def test_put_overwrites_existing(backend):
    backend.put("game/turn", 99)
    assert backend.get("game/turn") == 99


def test_put_array_append(backend):
    backend.put("planets/sol/earth/moons/@1", "NewMoon")  # index 1 = append (len was 1)
    assert backend.get("planets/sol/earth/moons") == ["Luna", "NewMoon"]


def test_put_array_set_existing(backend):
    backend.put("planets/sol/earth/moons/@0", "Moon")
    assert backend.get("planets/sol/earth/moons/@0") == "Moon"


def test_delete_removes_node(backend):
    backend.delete("planets/sol/mars")
    with pytest.raises(NotFoundError):
        backend.get("planets/sol/mars")
    assert backend.get("planets/sol/earth") is not None


def test_delete_array_element(backend):
    backend.delete("planets/sol/mars/moons/@0")
    assert backend.get("planets/sol/mars/moons") == ["Deimos"]


def test_delete_root_clears(backend):
    backend.delete("")
    assert backend.get("") == {}


def test_delete_missing_raises(backend):
    with pytest.raises(NotFoundError):
        backend.delete("nonexistent")


def test_list_root(backend):
    keys = backend.list("")
    assert set(keys) == {"game", "planets"}


def test_list_prefix(backend):
    assert backend.list("planets/sol") == ["earth", "mars"]
    assert set(backend.list("planets/sol/earth")) == {"name", "moons"}


def test_list_array_returns_index_segments(backend):
    assert backend.list("planets/sol/earth/moons") == ["@0"]
    assert backend.list("planets/sol/mars/moons") == ["@0", "@1"]


def test_list_missing_raises(backend):
    with pytest.raises(NotFoundError):
        backend.list("missing/prefix")


def test_empty_initial():
    be = MemoryAssetBackend(initial={})
    assert be.get("") == {}
    be.put("a/b", 1)
    assert be.get("a/b") == 1
