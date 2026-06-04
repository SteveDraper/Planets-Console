"""Inference corpus harness for real-turn military score build regression."""

from tests.inference_corpus.complexity import parse_max_complexity
from tests.inference_corpus.discovery import discover_cases, discover_cases_for_game
from tests.inference_corpus.manifest import load_manifest
from tests.inference_corpus.models import (
    CaseOutcome,
    CorpusCaseResult,
    CorpusReport,
    DiscoveredCase,
    ManifestCase,
)
from tests.inference_corpus.report import (
    case_result_to_dict,
    report_to_json,
    run_fixed_corpus,
    run_local_corpus,
)

__all__ = [
    "CaseOutcome",
    "CorpusCaseResult",
    "CorpusReport",
    "DiscoveredCase",
    "ManifestCase",
    "case_result_to_dict",
    "discover_cases",
    "discover_cases_for_game",
    "load_manifest",
    "parse_max_complexity",
    "report_to_json",
    "run_fixed_corpus",
    "run_local_corpus",
]
