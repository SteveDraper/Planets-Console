"""Process-pool worker entry points for local inference corpus runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from api.services.store_service import StoreService

from tests.inference_corpus.models import ComplexityLevel, CorpusCaseResult, DiscoveredCase
from tests.inference_corpus.run import run_discovered_case
from tests.inference_corpus.storage_loader import (
    configure_file_storage,
    make_game_service,
    make_turn_load_service,
)


@dataclass(frozen=True)
class DiscoveredCaseJob:
    case: DiscoveredCase
    storage_root: str
    max_complexity: ComplexityLevel
    include_adjunct: bool
    num_search_workers: int | None = None


def run_discovered_case_job(job: DiscoveredCaseJob) -> CorpusCaseResult:
    """Run one discovered case in an isolated worker process."""
    if job.num_search_workers is not None:
        os.environ["MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS"] = str(job.num_search_workers)
    else:
        os.environ.pop("MILITARY_SCORE_INFERENCE_NUM_SEARCH_WORKERS", None)

    storage_root = Path(job.storage_root)
    storage = configure_file_storage(storage_root=storage_root)
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    store = StoreService(storage)
    return run_discovered_case(
        job.case,
        turn_load=turn_load,
        game_service=game_service,
        store=store,
        max_complexity=job.max_complexity,
        include_adjunct=job.include_adjunct,
    )
