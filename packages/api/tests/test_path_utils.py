"""Unit tests for path resolution and @ segment rules."""
import pytest

from api.errors import NotFoundError, ValidationError
from api.storage.path_utils import (
    deep_copy_value,
    list_children,
    parse_index_segment,
    resolve_path,
    validate_no_reserved_at_keys,
)


def test_parse_index_segment_valid():
    assert parse_index_segment("@0") == 0
    assert parse_index_segment("@1") == 1
    assert parse_index_segment("@-1") == -1
    assert parse_index_segment("@42") == 42


def test_parse_index_segment_invalid_raises():
    with pytest.raises(ValidationError, match="Invalid path segment"):
        parse_index_segment("@abc")
    with pytest.raises(ValidationError, match="Invalid path segment"):
        parse_index_segment("@")
    with pytest.raises(ValidationError, match="Invalid path segment"):
        parse_index_segment("@1.5")


def test_resolve_path_empty_returns_root():
    root = {"a": 1}
    assert resolve_path(root, "") == root
    assert resolve_path(root, "   ") == root


def test_resolve_path_object_keys():
    root = {"game": {"turn": 2}, "planets": {"sol": {"earth": {"name": "Earth"}}}}
    assert resolve_path(root, "game") == {"turn": 2}
    assert resolve_path(root, "game/turn") == 2
    assert resolve_path(root, "planets/sol/earth/name") == "Earth"


def test_resolve_path_array_index():
    root = {"arr": [10, 20, 30]}
    assert resolve_path(root, "arr/@0") == 10
    assert resolve_path(root, "arr/@1") == 20
    assert resolve_path(root, "arr/@-1") == 30
    assert resolve_path(root, "arr/@-2") == 20


def test_resolve_path_array_index_out_of_range_404():
    root = {"arr": [10, 20]}
    with pytest.raises(NotFoundError, match="Array index out of range"):
        resolve_path(root, "arr/@5")
    with pytest.raises(NotFoundError, match="Array index out of range"):
        resolve_path(root, "arr/@-10")


def test_resolve_path_index_into_non_array_422():
    root = {"obj": {"x": 1}}
    with pytest.raises(ValidationError, match="not an array"):
        resolve_path(root, "obj/@0")


def test_resolve_path_malformed_index_segment_422():
    root = {"arr": [1]}
    with pytest.raises(ValidationError, match="expected @integer"):
        resolve_path(root, "arr/@abc")


def test_resolve_path_missing_key_404():
    root = {"a": 1}
    with pytest.raises(NotFoundError, match="Path does not exist"):
        resolve_path(root, "b")
    with pytest.raises(NotFoundError):
        resolve_path(root, "a/c")


def test_list_children_object():
    node = {"earth": {}, "mars": {}}
    assert list_children(node) == ["earth", "mars"]


def test_list_children_array():
    node = ["a", "b", "c"]
    assert list_children(node) == ["@0", "@1", "@2"]


def test_list_children_primitive():
    assert list_children(42) == []
    assert list_children("hello") == []
    assert list_children(None) == []


def test_validate_no_reserved_at_keys_accepts_normal():
    validate_no_reserved_at_keys({"a": 1, "b": {"c": 2}})
    validate_no_reserved_at_keys([1, 2, {"x": 3}])


def test_validate_no_reserved_at_keys_rejects_at_key():
    with pytest.raises(ValidationError, match="must not start with '@'"):
        validate_no_reserved_at_keys({"@reserved": 1})
    with pytest.raises(ValidationError, match="must not start with '@'"):
        validate_no_reserved_at_keys({"nested": {"@0": "bad"}})


def test_deep_copy_value():
    orig = {"a": [1, {"b": 2}]}
    copy = deep_copy_value(orig)
    assert copy == orig
    assert copy is not orig
    copy["a"][1]["b"] = 99
    assert orig["a"][1]["b"] == 2
