"""Codecs for persisted inference hull catalog mask overrides."""

from __future__ import annotations

from dataclasses import dataclass

from dacite import from_dict

from api.serialization.codecs import DACITE_CONFIG, dataclass_to_json


@dataclass
class InferenceHullCatalogMaskOverride:
    enabled_hull_ids: list[int]


def inference_hull_catalog_mask_override_from_json(data: dict) -> InferenceHullCatalogMaskOverride:
    return from_dict(
        data_class=InferenceHullCatalogMaskOverride,
        data=data,
        config=DACITE_CONFIG,
    )


def inference_hull_catalog_mask_override_to_json(
    override: InferenceHullCatalogMaskOverride,
) -> dict:
    return dataclass_to_json(override)
