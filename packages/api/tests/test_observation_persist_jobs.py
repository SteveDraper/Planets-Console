"""Observation_leg + persist timing used by the console-package occupancy probe."""

from __future__ import annotations

from api.analytics.fleet.observation_persist_jobs import time_observation_persist_jobs
from api.storage.file_json_jobs import (
    open_probe_file_backend,
    synthetic_large_fleet_document,
)


def test_time_observation_persist_jobs_reports_keys_and_small_document_walls(tmp_path):
    document = synthetic_large_fleet_document(min_bytes=8_000, min_nodes=400)
    timing = time_observation_persist_jobs(
        open_probe_file_backend(tmp_path / "observation-persist"),
        document=document,
    )
    assert timing.encoded_bytes >= 8_000
    assert timing.node_count >= 400
    assert timing.player_count == 11
    assert timing.record_count >= 1
    assert timing.observation_leg_seconds > 0.0
    assert timing.persist_seconds > 0.0
    assert timing.total_seconds == timing.observation_leg_seconds + timing.persist_seconds
    wire = timing.to_probe_json()
    assert wire["encodedBytes"] == timing.encoded_bytes
    assert wire["recordCount"] == timing.record_count
    assert set(wire) == {
        "encodedBytes",
        "nodeCount",
        "playerCount",
        "recordCount",
        "observationLegSeconds",
        "persistSeconds",
        "totalSeconds",
    }
