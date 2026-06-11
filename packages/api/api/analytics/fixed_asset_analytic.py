"""Base type for analytics that load static files from ``assets/analytics/{id}/``."""

from __future__ import annotations

from abc import ABC
from pathlib import Path
from typing import ClassVar

from api.analytics.assets import analytics_assets_dir


class FixedAssetAnalytic(ABC):
    """Analytic (or analytic subpackage) with repo-root assets under its canonical id.

    Subclasses must set ``ANALYTIC_ID`` to the directory name under
    ``assets/analytics/``. Asset loaders must resolve paths only via
    :meth:`assets_dir` -- never pass a different string to
    :func:`~api.analytics.assets.analytics_assets_dir`.
    """

    ANALYTIC_ID: ClassVar[str]

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        analytic_id = getattr(cls, "ANALYTIC_ID", "")
        if not isinstance(analytic_id, str) or not analytic_id:
            raise TypeError(f"{cls.__name__} must define a non-empty ANALYTIC_ID class variable")

    @classmethod
    def assets_dir(cls) -> Path:
        return analytics_assets_dir(cls.ANALYTIC_ID)
