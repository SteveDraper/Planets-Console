"""Ephemeral backend tests: deep-copy isolation and asset initialization."""

import json
from dataclasses import replace

import pytest
from api.config import ApiConfig, get_config, set_config
from api.errors import NotFoundError, ValidationError
from api.storage.memory_asset import MemoryAssetBackend
from api.storage.migrations import (
    DEFAULT_STORAGE_FORMAT,
    STORAGE_VERSION_KEY,
    MigrationContext,
    StorageFormat,
    StorageMigration,
)
from api.storage_factory import clear_backend_cache, get_storage

INFO = "games/sample/info"
NESTED = f"{INFO}/nested"
_FLEET_PLAYER_PATTERN = (
    "games",
    "*",
    "*",
    "turns",
    "*",
    "analytics",
    "fleet",
    "*",
)


def _fleet_step_format() -> tuple[list[int], StorageFormat]:
    calls: list[int] = []

    def handler(_context: MigrationContext) -> None:
        calls.append(1)

    storage_format = replace(
        DEFAULT_STORAGE_FORMAT,
        migrations=(
            StorageMigration(
                version=1,
                introduced_pattern=_FLEET_PLAYER_PATTERN,
                structural_handler=handler,
            ),
        ),
    )
    return calls, storage_format


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
            },
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
    assert backend.list("") == ["games", "meta"]


def test_current_layout_seed_is_stamped_without_migration():
    calls, storage_format = _fleet_step_format()
    ledger = {"ledger": {"playerId": 4}}
    backend = MemoryAssetBackend(
        initial={
            "games": {
                "1": {
                    "2": {
                        "turns": {
                            "3": {"analytics": {"fleet": {"4": ledger}}},
                        }
                    }
                }
            }
        },
        storage_format=storage_format,
    )
    assert calls == []
    assert backend.get("games/1/2/turns/3/analytics/fleet/4") == ledger
    assert backend.get(STORAGE_VERSION_KEY) == {"version": storage_format.current_version}


def test_legacy_shaped_seed_is_stamped_without_migration():
    calls, storage_format = _fleet_step_format()
    backend = MemoryAssetBackend(
        initial={
            "games": {
                "1": {
                    "2": {
                        "turns": {
                            "3": {
                                "analytics": {
                                    "fleet": {
                                        "analyticId": "fleet",
                                        "gameId": 1,
                                        "perspective": 2,
                                        "turn": 3,
                                        "ledgers": {"4": {"ledger": {"playerId": 4}}},
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        storage_format=storage_format,
    )
    assert calls == []
    assert backend.get(STORAGE_VERSION_KEY) == {"version": storage_format.current_version}
    with pytest.raises(NotFoundError):
        backend.get("games/1/2/turns/3/analytics/fleet/4")


def test_seed_stamps_the_bound_format_version():
    storage_format = replace(DEFAULT_STORAGE_FORMAT, current_version=0, migrations=())
    backend = MemoryAssetBackend(
        initial={"games": {"1": {"info": {"name": "keep"}}}},
        storage_format=storage_format,
    )
    assert backend.get("games/1/info") == {"name": "keep"}
    assert backend.get(STORAGE_VERSION_KEY) == {"version": 0}


@pytest.mark.parametrize(
    "seed",
    [
        {"meta": {}},
        {"meta": {"storage-version": {"version": 0}}},
        {"meta": {"storage-version": {"version": 1}}},
        {"meta": {"other": True}, "games": {"1": {"info": {"name": "keep"}}}},
    ],
)
def test_seed_rejects_meta_namespace(seed):
    with pytest.raises(ValidationError, match="must not contain the 'meta' namespace"):
        MemoryAssetBackend(initial=seed)


def test_seed_allows_meta_key_inside_a_document():
    backend = MemoryAssetBackend(
        initial={"games": {"1": {"info": {"name": "keep", "meta": {"x": 1}}}}}
    )
    assert backend.get("games/1/info") == {"name": "keep", "meta": {"x": 1}}
    assert backend.get(STORAGE_VERSION_KEY) == {"version": DEFAULT_STORAGE_FORMAT.current_version}


def test_storage_asset_path_meta_namespace_is_rejected(tmp_path):
    asset = tmp_path / "seed.json"
    asset.write_text(
        json.dumps({"meta": {"storage-version": {"version": 0}}}),
        encoding="utf-8",
    )
    previous = get_config()
    set_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=str(asset),
            include_dummy_data=False,
        )
    )
    clear_backend_cache()
    try:
        with pytest.raises(ValidationError, match="must not contain the 'meta' namespace"):
            get_storage()
    finally:
        clear_backend_cache()
        set_config(previous)
