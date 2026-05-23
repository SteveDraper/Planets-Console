"""Unit tests for StoreService: create/read/update/delete semantics and merge."""

import copy

import pytest
from api.errors import ConflictError, NotFoundError, ValidationError
from api.services.store_service import StoreService
from api.storage.memory_asset import MemoryAssetBackend

INFO = "games/sample/info"
NESTED = f"{INFO}/nested"


@pytest.fixture
def service():
    return StoreService(
        storage=MemoryAssetBackend(
            initial=copy.deepcopy(
                {
                    "games": {
                        "sample": {
                            "info": {
                                "turn": 2,
                                "nested": {
                                    "earth": {"name": "Earth"},
                                    "arr": [1, 2, 3],
                                },
                            }
                        }
                    }
                }
            )
        )
    )


def test_create_new_path(service):
    service.create(f"{INFO}/settings", {"value": 42})
    assert service.read(f"{INFO}/settings") == {"value": 42}


def test_create_raises_conflict_if_exists(service):
    with pytest.raises(ConflictError, match="already exists"):
        service.create(INFO, {"overwrite": True})


def test_create_rejects_reserved_at_key(service):
    with pytest.raises(ValidationError, match="must not start with '@'"):
        service.create(f"{INFO}/x", {"@bad": 1})


def test_read_existing(service):
    assert service.read(f"{INFO}/turn") == 2
    assert service.read(f"{NESTED}/earth/name") == "Earth"


def test_read_missing_raises(service):
    with pytest.raises(NotFoundError):
        service.read("games/missing/info")


def test_read_shallow_object(service):
    shallow = service.read_shallow(NESTED)
    assert shallow["path"] == NESTED
    assert shallow["node_type"] == "object"
    assert set(shallow["children"]) == {"earth", "arr"}
    assert shallow["count"] == 2


def test_read_shallow_array(service):
    shallow = service.read_shallow(f"{NESTED}/arr")
    assert shallow["node_type"] == "array"
    assert shallow["children"] == ["@0", "@1", "@2"]
    assert shallow["count"] == 3


def test_update_merge_objects(service):
    service.update(f"{NESTED}/earth", {"moons": ["Luna"], "name": "Earth Updated"})
    node = service.read(f"{NESTED}/earth")
    assert node["name"] == "Earth Updated"
    assert node["moons"] == ["Luna"]


def test_update_replace_array(service):
    service.update(f"{NESTED}/arr", [10, 20])
    assert service.read(f"{NESTED}/arr") == [10, 20]


def test_update_append_array(service):
    service.update(f"{NESTED}/arr", 4, merge_array="append")
    assert service.read(f"{NESTED}/arr") == [1, 2, 3, 4]


def test_update_prepend_array(service):
    service.update(f"{NESTED}/arr", 0, merge_array="prepend")
    assert service.read(f"{NESTED}/arr") == [0, 1, 2, 3]


def test_update_type_change_object_to_array_raises(service):
    with pytest.raises(ConflictError, match="change node type"):
        service.update(f"{NESTED}/earth", [1, 2])


def test_update_type_change_array_to_object_raises(service):
    with pytest.raises(ConflictError, match="change node type"):
        service.update(f"{NESTED}/arr", {"a": 1})


def test_update_primitive_to_object_raises(service):
    with pytest.raises(ConflictError, match="primitive/null to object"):
        service.update(f"{INFO}/turn", {"nested": 1})


def test_update_rejects_reserved_at_key(service):
    with pytest.raises(ValidationError, match="must not start with '@'"):
        service.update(INFO, {"@key": 1})


def test_update_missing_raises(service):
    with pytest.raises(NotFoundError):
        service.update("games/missing/info/x", 1)


def test_delete(service):
    service.delete(f"{NESTED}/earth")
    with pytest.raises(NotFoundError):
        service.read(f"{NESTED}/earth")


def test_delete_missing_raises(service):
    with pytest.raises(NotFoundError):
        service.delete("games/missing/info")
