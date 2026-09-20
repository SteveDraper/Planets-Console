"""Inference prior mining pipeline."""

from __future__ import annotations

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "default_assets_dir": (
        "api.analytics.military_score_inference.prior_mining.runner",
        "default_assets_dir",
    ),
    "run_prior_miner": (
        "api.analytics.military_score_inference.prior_mining.runner",
        "run_prior_miner",
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
