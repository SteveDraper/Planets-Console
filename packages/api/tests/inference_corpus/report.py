"""Aggregate inference corpus case results into a structured report."""

from pathlib import Path

from tests.inference_corpus.manifest import DEFAULT_MANIFEST_PATH, load_manifest
from tests.inference_corpus.models import ComplexityLevel, CorpusReport
from tests.inference_corpus.run import run_manifest_case


def run_fixed_corpus(
    *,
    manifest_path: Path | None = None,
    max_complexity: ComplexityLevel = "heavy",
    include_adjunct: bool = False,
) -> CorpusReport:
    """Run every case listed in the fixed corpus manifest."""
    _, cases = load_manifest(manifest_path or DEFAULT_MANIFEST_PATH)
    report = CorpusReport()
    for case in cases:
        report.results.append(
            run_manifest_case(
                case,
                max_complexity=max_complexity,
                include_adjunct=include_adjunct,
            )
        )
    return report
