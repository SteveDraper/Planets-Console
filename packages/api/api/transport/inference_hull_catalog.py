"""HTTP transport models for inference hull catalog masks."""

from pydantic import BaseModel, Field


class InferenceHullCatalogMaskUpdateRequest(BaseModel):
    enabled_hull_ids: list[int] = Field(alias="enabledHullIds")

    model_config = {"populate_by_name": True}
