"""Inference corpus harness for real-turn military score build regression."""

from tests.inference_corpus.manifest import load_manifest
from tests.inference_corpus.models import (
    CaseOutcome,
    CorpusCaseResult,
    CorpusReport,
    ManifestCase,
)
from tests.inference_corpus.report import run_fixed_corpus

__all__ = [
    "CaseOutcome",
    "CorpusCaseResult",
    "CorpusReport",
    "ManifestCase",
    "load_manifest",
    "run_fixed_corpus",
]
