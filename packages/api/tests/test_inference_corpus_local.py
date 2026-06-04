"""Integration tests for local inference corpus runs against storage."""

import json

import pytest
from api.services.store_service import StoreService
from api.storage.file import FileStorageBackend

from tests.inference_corpus.manifest import FIXTURES_ROOT
from tests.inference_corpus.models import CaseOutcome
from tests.inference_corpus.report import run_local_corpus
from tests.inference_corpus.storage_loader import (
    configure_file_storage,
    make_game_service,
    make_turn_load_service,
)


@pytest.fixture
def local_corpus_storage(tmp_path):
    storage_root = tmp_path / "data"
    backend = FileStorageBackend(storage_root)
    fixture_game_root = FIXTURES_ROOT / "628580"
    backend.put("games/628580/info", json.loads((fixture_game_root / "info.json").read_text()))
    for turn_number in (2, 3):
        turn_src = fixture_game_root / "1" / "turns" / f"{turn_number}.json"
        backend.put(
            f"games/628580/1/turns/{turn_number}",
            json.loads(turn_src.read_text()),
        )
    configure_file_storage(storage_root=storage_root)
    return storage_root


def test_run_local_corpus_discovers_and_passes_seed_case(local_corpus_storage):
    storage = configure_file_storage(storage_root=local_corpus_storage)
    turn_load = make_turn_load_service(storage)
    game_service = make_game_service(storage)
    store = StoreService(storage)

    report = run_local_corpus(
        store=store,
        turn_load=turn_load,
        game_service=game_service,
        game_id=628580,
        max_complexity="heavy",
    )

    assert len(report.results) == 1
    result = report.results[0]
    assert result.case_id == "628580-p1-host2"
    assert result.outcome == CaseOutcome.PASSED
    assert result.complexity == "routine"
    assert result.status == "exact"


def test_run_local_corpus_skips_adjunct_by_default(local_corpus_storage, monkeypatch):
    from tests.inference_corpus import run as run_module

    def always_adjunct(*args, **kwargs):
        return ("adjunct", ("forced_adjunct",))

    monkeypatch.setattr(run_module, "classify_complexity", always_adjunct)

    storage = configure_file_storage(storage_root=local_corpus_storage)
    report = run_local_corpus(
        store=StoreService(storage),
        turn_load=make_turn_load_service(storage),
        game_service=make_game_service(storage),
        game_id=628580,
    )

    assert report.results[0].outcome == CaseOutcome.SKIPPED_COMPLEXITY
    assert report.results[0].skip_reason == "adjunct_disabled"
