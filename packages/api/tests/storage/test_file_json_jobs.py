"""Large-document file-backend timing used by the console-package occupancy probe."""

from __future__ import annotations

import json

from api.storage.file_json_jobs import (
    LARGE_DOCUMENT_TARGET_BYTES,
    LARGE_DOCUMENT_TARGET_NODES,
    json_node_count,
    synthetic_large_fleet_document,
    time_file_json_jobs,
    time_large_document_jobs,
)

FILE_MAX_THROUGHPUT_RATIO = 3.0


def test_synthetic_large_fleet_document_meets_683364_size_floors():
    document = synthetic_large_fleet_document()
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    ledgers = document["ledgers"]
    assert isinstance(ledgers, dict)
    assert len(ledgers) == 11
    assert len(encoded) >= LARGE_DOCUMENT_TARGET_BYTES
    assert json_node_count(document) >= LARGE_DOCUMENT_TARGET_NODES


def test_time_file_json_jobs_tiny_mix_counts(tmp_path):
    timing = time_file_json_jobs(tmp_path / "tiny", job_count=3)
    assert timing.job_count == 3
    assert timing.wall_seconds > 0.0
    assert timing.protocol_counts == {"get": 6, "list": 3, "put": 5}


def test_time_large_document_jobs_reports_gil_serial_get_and_loads(tmp_path):
    document = synthetic_large_fleet_document(min_bytes=8_000, min_nodes=400)
    timing = time_large_document_jobs(
        tmp_path / "large",
        document=document,
        iterations=2,
        worker_count=8,
    )
    assert timing.encoded_bytes >= 8_000
    assert timing.node_count >= 400
    assert timing.player_count == 11
    assert timing.iterations == 2
    assert timing.worker_count == 8
    assert timing.json_loads_single_seconds > 0.0
    assert timing.deep_copy_single_seconds > 0.0
    assert timing.get_single_seconds > 0.0
    assert timing.put_single_seconds > 0.0
    assert timing.json_loads_throughput_ratio <= FILE_MAX_THROUGHPUT_RATIO
    assert timing.deep_copy_throughput_ratio <= FILE_MAX_THROUGHPUT_RATIO
    assert timing.get_throughput_ratio <= FILE_MAX_THROUGHPUT_RATIO
    wire = timing.to_probe_json()
    assert wire["encodedBytes"] == timing.encoded_bytes
    assert wire["getThroughputRatio"] == timing.get_throughput_ratio
