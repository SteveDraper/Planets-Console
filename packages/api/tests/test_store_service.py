"""Unit tests for StoreService: create/read/update/delete semantics and merge."""

import copy

import pytest
from api.errors import ConflictError, NotFoundError, ValidationError
from api.services.store_service import StoreService
from api.storage.memory_asset import MemoryAssetBackend

INITIAL = {
    "game": {"turn": 2},
    "planets": {"sol": {"earth": {"name": "Earth"}, "arr": [1, 2, 3]}},
}


@pytest.fixture
def service():
    return StoreService(storage=MemoryAssetBackend(initial=copy.deepcopy(INITIAL)))


def test_create_new_path(service):
    service.create("new/key", {"value": 42})
    assert service.read("new/key") == {"value": 42}


def test_create_raises_conflict_if_exists(service):
    with pytest.raises(ConflictError, match="already exists"):
        service.create("game", {"overwrite": True})


def test_create_rejects_reserved_at_key(service):
    with pytest.raises(ValidationError, match="must not start with '@'"):
        service.create("x", {"@bad": 1})


def test_read_existing(service):
    assert service.read("game/turn") == 2
    assert service.read("planets/sol/earth/name") == "Earth"


def test_read_missing_raises(service):
    with pytest.raises(NotFoundError):
        service.read("missing")


def test_read_shallow_object(service):
    shallow = service.read_shallow("planets/sol")
    assert shallow["path"] == "planets/sol"
    assert shallow["node_type"] == "object"
    assert set(shallow["children"]) == {"earth", "arr"}
    assert shallow["count"] == 2


def test_read_shallow_array(service):
    shallow = service.read_shallow("planets/sol/arr")
    assert shallow["node_type"] == "array"
    assert shallow["children"] == ["@0", "@1", "@2"]
    assert shallow["count"] == 3


def test_update_merge_objects(service):
    service.update("planets/sol/earth", {"moons": ["Luna"], "name": "Earth Updated"})
    node = service.read("planets/sol/earth")
    assert node["name"] == "Earth Updated"
    assert node["moons"] == ["Luna"]


def test_update_replace_array(service):
    service.update("planets/sol/arr", [10, 20])
    assert service.read("planets/sol/arr") == [10, 20]


def test_update_append_array(service):
    service.update("planets/sol/arr", 4, merge_array="append")
    assert service.read("planets/sol/arr") == [1, 2, 3, 4]


def test_update_prepend_array(service):
    service.update("planets/sol/arr", 0, merge_array="prepend")
    assert service.read("planets/sol/arr") == [0, 1, 2, 3]


def test_update_type_change_object_to_array_raises(service):
    with pytest.raises(ConflictError, match="change node type"):
        service.update("planets/sol/earth", [1, 2])


def test_update_type_change_array_to_object_raises(service):
    with pytest.raises(ConflictError, match="change node type"):
        service.update("planets/sol/arr", {"a": 1})


def test_update_primitive_to_object_raises(service):
    with pytest.raises(ConflictError, match="primitive/null to object"):
        service.update("game/turn", {"nested": 1})


def test_update_rejects_reserved_at_key(service):
    with pytest.raises(ValidationError, match="must not start with '@'"):
        service.update("game", {"@key": 1})


def test_update_missing_raises(service):
    with pytest.raises(NotFoundError):
        service.update("missing", 1)


def test_delete(service):
    service.delete("planets/sol/earth")
    with pytest.raises(NotFoundError):
        service.read("planets/sol/earth")


def test_delete_missing_raises(service):
    with pytest.raises(NotFoundError):
        service.delete("missing")
