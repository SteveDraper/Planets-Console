"""Tests for reading YAML asset documents."""

from __future__ import annotations

import pytest
import yaml
from api.serialization.yaml_documents import load_yaml_mapping


def test_load_yaml_mapping_returns_the_root_mapping(tmp_path):
    path = tmp_path / "asset.yaml"
    path.write_text("version: 2\nhulls:\n  - id: 15\n    name: Small Deep Space Freighter\n")

    assert load_yaml_mapping(path, document_name="test asset") == {
        "version": 2,
        "hulls": [{"id": 15, "name": "Small Deep Space Freighter"}],
    }


@pytest.mark.parametrize("body", ["- 1\n- 2\n", "just text\n", ""])
def test_load_yaml_mapping_refuses_a_root_that_is_not_a_mapping(tmp_path, body):
    path = tmp_path / "asset.yaml"
    path.write_text(body)

    with pytest.raises(ValueError, match="test asset root must be a mapping"):
        load_yaml_mapping(path, document_name="test asset")


def test_load_yaml_mapping_refuses_python_object_tags(tmp_path):
    path = tmp_path / "asset.yaml"
    path.write_text("payload: !!python/object/apply:os.getcwd []\n")

    with pytest.raises(yaml.constructor.ConstructorError):
        load_yaml_mapping(path, document_name="test asset")
