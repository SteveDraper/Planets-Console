"""Seed the in-memory store with dummy data from static JSON assets."""

import json
import logging
from pathlib import Path

from api.storage.base import StorageBackend

logger = logging.getLogger(__name__)

_ASSETS_DIR = Path(__file__).resolve().parent.parent / "storage" / "assets"

_SEED_MAP = {
    "game_info_sample.json": "games/628580/info",
    "turn_sample.json": "games/628580/1/turns/111",
}


def seed_dummy_data(storage: StorageBackend) -> None:
    """Load static JSON assets and put them into the store at well-known paths."""
    for filename, store_path in _SEED_MAP.items():
        asset_path = _ASSETS_DIR / filename
        if not asset_path.is_file():
            logger.warning("Seed asset not found: %s", asset_path)
            continue
        with open(asset_path, encoding="utf-8") as f:
            data = json.load(f)
        storage.put(store_path, data)
        logger.info("Seeded store path %r from %s", store_path, filename)
