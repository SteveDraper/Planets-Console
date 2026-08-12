"""FileStorageBackend-specific tests: layout, atomic write, prune, registry."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from api.errors import NotFoundError, ValidationError
from api.storage.file import FileStorageBackend

GAME_INFO = "games/628580/info"
TURN = "games/628580/1/turns/111"


@pytest.fixture
def storage_root(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def backend(storage_root):
    return FileStorageBackend(storage_root)


def test_document_paths_on_disk(backend, storage_root):
    backend.put(GAME_INFO, {"name": "Serada"})
    backend.put(TURN, {"turn": 111})

    info_path = storage_root / "games" / "628580" / "info.json"
    turn_path = storage_root / "games" / "628580" / "1" / "turns" / "111.json"
    assert info_path.is_file()
    assert turn_path.is_file()
    assert json.loads(info_path.read_text(encoding="utf-8")) == {"name": "Serada"}
    assert json.loads(turn_path.read_text(encoding="utf-8")) == {"turn": 111}


def test_nested_path_stored_inside_document(backend, storage_root):
    backend.put(f"{GAME_INFO}/settings", {"x": 1})
    info_path = storage_root / "games" / "628580" / "info.json"
    assert json.loads(info_path.read_text(encoding="utf-8")) == {
        "settings": {"x": 1},
    }


def test_atomic_write_uses_temp_then_replace(backend, storage_root):
    target = storage_root / "games" / "628580" / "info.json"
    calls: list[str] = []

    original_replace = __import__("os").replace

    def tracking_replace(src, dst):
        calls.append(f"{Path(src).name}->{Path(dst).name}")
        return original_replace(src, dst)

    with patch("api.storage.file.os.replace", side_effect=tracking_replace):
        backend.put(GAME_INFO, {"name": "A"})

    assert target.is_file()
    assert any("tmp" in call for call in calls)


def test_ensure_dir_retries_file_exists_after_concurrent_prune(backend, storage_root):
    """CPython mkdir TOCTOU: EEXIST then is_dir False when a peer pruned the dir."""
    parent = storage_root / "games" / "628580" / "1" / "turns" / "111" / "analytics"
    calls = {"n": 0}
    real_mkdir = Path.mkdir

    def flaky_mkdir(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileExistsError(17, "File exists", str(self))
        return real_mkdir(self, *args, **kwargs)

    with patch.object(Path, "mkdir", flaky_mkdir):
        with patch.object(Path, "is_dir", return_value=False):
            with patch.object(Path, "exists", return_value=False):
                FileStorageBackend._ensure_dir(parent)

    assert calls["n"] >= 2


def test_ensure_dir_raises_when_path_is_a_file(backend, storage_root):
    storage_root.mkdir(parents=True, exist_ok=True)
    blocker = storage_root / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError):
        FileStorageBackend._ensure_dir(blocker)


def test_get_maps_file_not_found_during_open_to_not_found(backend, storage_root):
    """Peer unlink between exists-check and open must be NotFoundError, not errno."""
    backend.put(GAME_INFO, {"name": "A"})
    target = storage_root / "games" / "628580" / "info.json"
    real_open = open

    def racing_open(path, *args, **kwargs):
        if Path(path) == target:
            raise FileNotFoundError(2, "No such file or directory", str(target))
        return real_open(path, *args, **kwargs)

    with patch("api.storage.file.open", side_effect=racing_open):
        with pytest.raises(NotFoundError, match="Document not found"):
            backend.get(GAME_INFO)


def test_put_nested_treats_vanished_document_as_empty(backend, storage_root):
    """Suffix put must create a new document when a peer unlinked during load."""
    backend.put(GAME_INFO, {"keep": 1})
    target = storage_root / "games" / "628580" / "info.json"
    real_open = open

    def unlink_on_read(path, *args, **kwargs):
        mode = args[0] if args else kwargs.get("mode", "r")
        if Path(path) == target and "w" not in str(mode):
            target.unlink()
            raise FileNotFoundError(2, "No such file or directory", str(target))
        return real_open(path, *args, **kwargs)

    with patch("api.storage.file.open", side_effect=unlink_on_read):
        backend.put(f"{GAME_INFO}/settings", {"x": 1})

    assert json.loads(target.read_text(encoding="utf-8")) == {"settings": {"x": 1}}


def test_atomic_write_retries_replace_file_not_found(backend, storage_root):
    """Parent prune between mkdir and replace is retried, matching _ensure_dir."""
    calls = {"n": 0}
    original_replace = __import__("os").replace

    def flaky_replace(src, dst):
        calls["n"] += 1
        if calls["n"] == 1:
            raise FileNotFoundError(2, "No such file or directory", str(dst))
        return original_replace(src, dst)

    with patch("api.storage.file.os.replace", side_effect=flaky_replace):
        backend.put(GAME_INFO, {"name": "A"})

    assert calls["n"] == 2
    target = storage_root / "games" / "628580" / "info.json"
    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "A"}


def test_delete_maps_concurrent_unlink_to_not_found(backend, storage_root):
    backend.put(GAME_INFO, {"name": "A"})
    real_unlink = Path.unlink

    def racing_unlink(self, *args, **kwargs):
        if self.name == "info.json":
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_unlink(self, *args, **kwargs)

    with patch.object(Path, "unlink", racing_unlink):
        with pytest.raises(NotFoundError, match="Document not found"):
            backend.delete(GAME_INFO)


def test_atomic_write_uses_unique_temp_name_per_write(backend, storage_root):
    temp_names: list[str] = []
    original_replace = __import__("os").replace

    def tracking_replace(src, dst):
        temp_names.append(Path(src).name)
        return original_replace(src, dst)

    with patch("api.storage.file.os.replace", side_effect=tracking_replace):
        backend.put(GAME_INFO, {"name": "A"})
        backend.put(GAME_INFO, {"name": "B"})

    assert len(temp_names) == 2
    assert temp_names[0] != temp_names[1]


def test_prune_empty_dirs_after_document_delete(backend, storage_root):
    backend.put(GAME_INFO, {"name": "A"})
    game_dir = storage_root / "games" / "628580"
    assert game_dir.is_dir()
    backend.delete(GAME_INFO)
    assert not (storage_root / "games" / "628580" / "info.json").exists()
    assert not game_dir.exists()
    assert not (storage_root / "games").exists()


def test_unregistered_put_leaves_no_files(backend, storage_root):
    with pytest.raises(ValidationError, match="Unregistered"):
        backend.put("orphan/path", {"x": 1})
    assert list(storage_root.rglob("*")) == []


def test_list_filesystem_prefix_before_document_exists(backend, storage_root):
    backend.put(TURN, {"turn": 111})
    assert backend.list("games/628580") == ["1"]


def test_list_turn_analytics_prefix_lists_analytic_documents(backend, storage_root):
    """…/turns/N/analytics is between breakpoints; list sibling docs, not turn keys."""
    backend.put(TURN, {"turn": 111, "ships": []})
    backend.put(f"{TURN}/analytics/fleet", {"ledgers": {}})
    backend.put(f"{TURN}/analytics/scores", {"inference_rows": {}})

    assert backend.list(f"{TURN}/analytics") == ["fleet", "scores"]
    # Turn document listing is unchanged.
    assert "ships" in backend.list(TURN)
    assert "analytics" not in backend.list(TURN)


def test_in_document_delete_rewrites_file(backend, storage_root):
    backend.put(GAME_INFO, {"keep": 1, "drop": 2})
    backend.delete(f"{GAME_INFO}/drop")
    assert json.loads((storage_root / "games" / "628580" / "info.json").read_text()) == {
        "keep": 1,
    }


def test_missing_document_raises_not_found(backend):
    with pytest.raises(NotFoundError):
        backend.get(GAME_INFO)


@pytest.mark.parametrize(
    "path",
    [
        "games/../info",
        "games/628580/../info",
        "games\\628580\\info",
        "games//628580/info",
    ],
)
def test_unsafe_path_segments_rejected_before_filesystem(backend, storage_root, path):
    with pytest.raises(ValidationError):
        backend.put(path, {"x": 1})
    with pytest.raises(ValidationError):
        backend.get(path)
    with pytest.raises(ValidationError):
        backend.list(path)
    assert list(storage_root.rglob("*")) == []
