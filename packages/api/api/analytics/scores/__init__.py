"""Core scoreboard analytic."""

from __future__ import annotations

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ANALYTIC_ID": ("api.analytics.scores_assets", "ANALYTIC_ID"),
    "REGISTRATION": ("api.analytics.scores.registration", "REGISTRATION"),
    "compute_scores_table": ("api.analytics.scores.registration", "compute_scores_table"),
    "get_scores_row_inference": (
        "api.analytics.scores.inference",
        "get_scores_row_inference",
    ),
    "get_scores_table": ("api.analytics.scores.registration", "get_scores_table"),
    "iter_scores_table_inference_stream": (
        "api.analytics.scores.registration",
        "iter_scores_table_inference_stream",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> object:
    spec = _LAZY_EXPORTS.get(name)
    if spec is not None:
        module_path, attr = spec
        import importlib

        module = importlib.import_module(module_path)
        return getattr(module, attr)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
