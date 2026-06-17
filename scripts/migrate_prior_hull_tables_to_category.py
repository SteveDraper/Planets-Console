#!/usr/bin/env python3
"""Migrate version 3 unconditional hull tables to version 4 category-keyed hull tables."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

_API_ROOT = Path(__file__).resolve().parents[1] / "packages" / "api"
sys.path.insert(0, str(_API_ROOT))

from api.analytics.military_score_inference.hull_category import (  # noqa: E402
    INFERENCE_HULL_CATEGORIES,
    resolve_inference_hull_category,
)
from api.analytics.military_score_inference.prior_mining.asset_write import (  # noqa: E402
    write_commented_prior_weights_asset,
)
from api.analytics.military_score_inference.prior_mining.component_name_catalog import (  # noqa: E402
    ComponentNameCatalogBuilder,
)
from api.analytics.military_score_inference.prior_weights_asset import (  # noqa: E402
    parse_prior_weights_document,
)
from api.analytics.military_score_inference.prior_weights_laplace import (  # noqa: E402
    WILDCARD_COUNT_KEY,
)
from api.models.components import Hull  # noqa: E402
from tests.inference_corpus.fixtures import load_turn_fixture  # noqa: E402


def _default_category_for_hull(hull: Hull) -> str:
    beam_count = hull.beams if hull.beams > 0 else 0
    launcher_count = hull.launchers if hull.launchers > 0 else 0
    return resolve_inference_hull_category(
        hull,
        beam_count=beam_count,
        launcher_count=launcher_count,
    )


def _is_legacy_flat_hull_counts(global_raw: dict[Any, Any]) -> bool:
    for value in global_raw.values():
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, dict):
            return False
    return False


def _migrate_flat_hull_counts(
    flat_counts: dict[Any, float],
    *,
    hulls_by_id: dict[int, Hull],
) -> dict[str, dict[int | str, float]]:
    by_category: dict[str, dict[int | str, float]] = {
        category: {} for category in INFERENCE_HULL_CATEGORIES
    }
    wildcard = flat_counts.get(WILDCARD_COUNT_KEY)
    for key, count in flat_counts.items():
        if key == WILDCARD_COUNT_KEY:
            continue
        if not isinstance(key, int):
            continue
        hull = hulls_by_id.get(key)
        if hull is None:
            continue
        category = _default_category_for_hull(hull)
        by_category[category][key] = by_category[category].get(key, 0.0) + float(count)
    if wildcard is not None:
        for category in INFERENCE_HULL_CATEGORIES:
            if by_category[category]:
                by_category[category][WILDCARD_COUNT_KEY] = float(wildcard)
    return {category: table for category, table in by_category.items() if table}


def _migrate_band_hull_tables(
    band_raw: dict[str, Any],
    *,
    hulls_by_id: dict[int, Hull],
) -> dict[str, Any]:
    migrated: dict[str, Any] = {}
    global_raw = band_raw.get("global", {})
    if not isinstance(global_raw, dict):
        raise ValueError("hulls band global must be a mapping")
    if _is_legacy_flat_hull_counts(global_raw):
        migrated["global"] = _migrate_flat_hull_counts(global_raw, hulls_by_id=hulls_by_id)
    else:
        migrated["global"] = global_raw
    by_race = band_raw.get("byRace")
    if isinstance(by_race, dict):
        migrated_by_race: dict[int, Any] = {}
        for race_id, race_raw in by_race.items():
            if not isinstance(race_raw, dict):
                continue
            if _is_legacy_flat_hull_counts(race_raw):
                migrated_by_race[int(race_id)] = _migrate_flat_hull_counts(
                    race_raw,
                    hulls_by_id=hulls_by_id,
                )
            else:
                migrated_by_race[int(race_id)] = race_raw
        if migrated_by_race:
            migrated["byRace"] = migrated_by_race
    return migrated


def migrate_document(
    document: dict[str, Any],
    *,
    hulls_by_id: dict[int, Hull],
) -> dict[str, Any]:
    version = document.get("version")
    if isinstance(version, int) and version >= 4:
        return document
    migrated = dict(document)
    migrated["version"] = 4
    hulls_raw = document.get("hulls", {})
    if not isinstance(hulls_raw, dict):
        raise ValueError("hulls must be a mapping")
    migrated["hulls"] = {
        band: _migrate_band_hull_tables(band_raw, hulls_by_id=hulls_by_id)
        for band, band_raw in hulls_raw.items()
        if isinstance(band_raw, dict)
    }
    return migrated


def migrate_prior_weights_file(
    path: Path,
    *,
    hulls_by_id: dict[int, Hull],
    rewrite_commented: bool,
) -> bool:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: root must be a mapping")
    if document.get("version", 0) >= 4 and not _band_needs_migration(document.get("hulls", {})):
        return False
    migrated = migrate_document(document, hulls_by_id=hulls_by_id)
    asset = parse_prior_weights_document(migrated, require_complete_aggregates=False)
    if rewrite_commented:
        write_commented_prior_weights_asset(
            path,
            asset,
            name_catalog=_name_catalog_from_turn_fixture(),
        )
    else:
        path.write_text(yaml.safe_dump(migrated, sort_keys=False), encoding="utf-8")
    return True


def _band_needs_migration(hulls_raw: object) -> bool:
    if not isinstance(hulls_raw, dict):
        return False
    for band_raw in hulls_raw.values():
        if not isinstance(band_raw, dict):
            continue
        global_raw = band_raw.get("global", {})
        if isinstance(global_raw, dict) and _is_legacy_flat_hull_counts(global_raw):
            return True
    return False


def _hulls_by_id_from_turn_fixture() -> dict[int, Hull]:
    turn = load_turn_fixture("628580/1/turns/3.json")
    return {hull.id: hull for hull in turn.hulls}


def _name_catalog_from_turn_fixture() -> Any:
    builder = ComponentNameCatalogBuilder()
    builder.absorb_turn(load_turn_fixture("628580/1/turns/3.json"))
    return builder.build()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help=(
            "Prior weight YAML files to migrate "
            "(default: assets/analytics/scores/prior_weights_*.yaml)"
        ),
    )
    parser.add_argument(
        "--plain-yaml",
        action="store_true",
        help="Write plain YAML instead of preserving comment annotations.",
    )
    args = parser.parse_args()

    default_assets = Path(__file__).resolve().parents[1] / "assets" / "analytics" / "scores"
    paths = args.paths or sorted(default_assets.glob("prior_weights_*.yaml"))
    paths = [path for path in paths if path.name != "prior_weights_asset.template.yaml"]
    hulls_by_id = _hulls_by_id_from_turn_fixture()

    migrated_any = False
    for path in paths:
        if not path.is_file():
            print(f"skip missing {path}", file=sys.stderr)
            continue
        changed = migrate_prior_weights_file(
            path,
            hulls_by_id=hulls_by_id,
            rewrite_commented=not args.plain_yaml,
        )
        if changed:
            migrated_any = True
            print(f"migrated {path}", file=sys.stderr)
        else:
            print(f"already v4 {path}", file=sys.stderr)

    if not migrated_any:
        print("no files migrated", file=sys.stderr)


if __name__ == "__main__":
    main()
