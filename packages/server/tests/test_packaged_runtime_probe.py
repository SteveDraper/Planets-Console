"""Packaged onedir probe: JSON contract and process-host argv."""

from __future__ import annotations

import json
import sys

from server.process_host.packaged_runtime_probe import run_packaged_runtime_probe
from server.process_host.runtime import main


def test_packaged_runtime_probe_json_reports_gil_file_jobs_and_interpreter_error(tmp_path):
    storage_root = tmp_path / "probe-store"
    payload = run_packaged_runtime_probe(storage_root=storage_root)

    assert payload["pythonProgressedDuringSolve"] in (True, False)
    assert payload["frozen"] is False
    assert isinstance(payload["sysExecutable"], str)
    assert payload["sysExecutable"]
    assert payload["fileJson"]["jobCount"] == 400
    assert payload["fileJson"]["wallSeconds"] > 0.0
    assert payload["fileJson"]["protocolCounts"]["get"] == 800
    assert payload["fileJson"]["protocolCounts"]["list"] == 400
    assert payload["fileJson"]["protocolCounts"]["put"] >= 1
    large = payload["largeDocument"]
    assert large["encodedBytes"] >= 775_000
    assert large["nodeCount"] >= 38_000
    assert large["playerCount"] == 11
    assert large["iterations"] == 8
    assert large["workerCount"] == 8
    assert large["jsonLoadsSingleSeconds"] > 0.0
    assert large["deepCopySingleSeconds"] > 0.0
    assert large["getSingleSeconds"] > 0.0
    assert large["putSingleSeconds"] > 0.0
    assert large["jsonLoadsThroughputRatio"] > 0.0
    assert large["getThroughputRatio"] > 0.0
    observation = payload["observationPersist"]
    assert observation["encodedBytes"] >= 775_000
    assert observation["nodeCount"] >= 38_000
    assert observation["playerCount"] == 11
    assert observation["recordCount"] >= 1
    assert observation["observationLegSeconds"] > 0.0
    assert observation["persistSeconds"] > 0.0
    assert observation["totalSeconds"] > 0.0
    assert payload["scoresSolve"] is None
    app_kit_on = payload["appKitOn"]
    assert app_kit_on["ran"] is False
    assert app_kit_on["pythonProgressedDuringSolve"] is None
    assert app_kit_on["gil"] is None
    assert app_kit_on["largeDocument"] is None
    assert app_kit_on["scoresSolve"] is None
    error = payload["interpreterPoolImportError"]
    assert error is None or isinstance(error, str)
    assert storage_root.is_dir()
    assert not (tmp_path / "Library").exists()


def test_main_console_package_probe_writes_output_and_skips_app(tmp_path, monkeypatch):
    output = tmp_path / "probe.json"
    started: list[str] = []
    data_dir_hits: list[object] = []
    monkeypatch.setattr(
        "server.process_host.runtime._run",
        lambda: started.append("run") or 0,
    )
    monkeypatch.setattr(
        "server.process_host.runtime.console_data_directory",
        lambda: data_dir_hits.append("data") or tmp_path / "Application Support",
    )
    monkeypatch.setattr(
        "server.process_host.packaged_runtime_probe.run_packaged_runtime_probe",
        lambda **_kwargs: {
            "pythonProgressedDuringSolve": True,
            "frozen": False,
            "sysExecutable": "/probe",
            "fileJson": {
                "jobCount": 400,
                "wallSeconds": 0.01,
                "protocolCounts": {"get": 800, "list": 400, "put": 5},
            },
            "largeDocument": {
                "encodedBytes": 775_000,
                "nodeCount": 38_000,
                "playerCount": 11,
                "iterations": 8,
                "workerCount": 8,
                "jsonLoadsSingleSeconds": 0.01,
                "jsonLoadsEightWallSeconds": 0.08,
                "jsonLoadsThroughputRatio": 1.0,
                "deepCopySingleSeconds": 0.01,
                "deepCopyEightWallSeconds": 0.08,
                "deepCopyThroughputRatio": 1.0,
                "getSingleSeconds": 0.01,
                "getEightWallSeconds": 0.08,
                "getThroughputRatio": 1.0,
                "putSingleSeconds": 0.02,
                "putEightWallSeconds": 0.16,
                "putThroughputRatio": 1.0,
            },
            "observationPersist": {
                "encodedBytes": 775_000,
                "nodeCount": 38_000,
                "playerCount": 11,
                "recordCount": 100,
                "observationLegSeconds": 0.01,
                "persistSeconds": 0.02,
                "totalSeconds": 0.03,
            },
            "scoresSolve": None,
            "appKitOn": {
                "ran": False,
                "pythonProgressedDuringSolve": None,
                "gil": None,
                "largeDocument": None,
                "scoresSolve": None,
            },
            "interpreterPoolImportError": None,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["process-host", "--console-package-probe", "--output", str(output)],
    )

    assert main() == 0
    assert started == []
    assert data_dir_hits == []
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["pythonProgressedDuringSolve"] is True
    assert payload["fileJson"]["jobCount"] == 400
    assert payload["largeDocument"]["encodedBytes"] == 775_000
    assert payload["observationPersist"]["encodedBytes"] == 775_000
    assert payload["appKitOn"]["ran"] is False
    assert not (tmp_path / "Application Support").exists()


def test_main_console_package_probe_forwards_scores_solve_tree(tmp_path, monkeypatch):
    output = tmp_path / "probe.json"
    tree = tmp_path / "game-tree"
    seen: list[object] = []
    monkeypatch.setattr(
        "server.process_host.runtime._run",
        lambda: 0,
    )
    monkeypatch.setattr(
        "server.process_host.packaged_runtime_probe.run_packaged_runtime_probe",
        lambda **kwargs: (
            seen.append(kwargs.get("scores_solve_tree"))
            or {
                "pythonProgressedDuringSolve": True,
                "frozen": False,
                "sysExecutable": "/probe",
                "fileJson": {
                    "jobCount": 400,
                    "wallSeconds": 0.01,
                    "protocolCounts": {"get": 800, "list": 400, "put": 5},
                },
                "largeDocument": {
                    "encodedBytes": 775_000,
                    "nodeCount": 38_000,
                    "playerCount": 11,
                    "iterations": 8,
                    "workerCount": 8,
                    "jsonLoadsSingleSeconds": 0.01,
                    "jsonLoadsEightWallSeconds": 0.08,
                    "jsonLoadsThroughputRatio": 1.0,
                    "deepCopySingleSeconds": 0.01,
                    "deepCopyEightWallSeconds": 0.08,
                    "deepCopyThroughputRatio": 1.0,
                    "getSingleSeconds": 0.01,
                    "getEightWallSeconds": 0.08,
                    "getThroughputRatio": 1.0,
                    "putSingleSeconds": 0.02,
                    "putEightWallSeconds": 0.16,
                    "putThroughputRatio": 1.0,
                },
                "observationPersist": {
                    "encodedBytes": 775_000,
                    "nodeCount": 38_000,
                    "playerCount": 11,
                    "recordCount": 100,
                    "observationLegSeconds": 0.01,
                    "persistSeconds": 0.02,
                    "totalSeconds": 0.03,
                },
                "scoresSolve": None,
                "appKitOn": {
                    "ran": False,
                    "pythonProgressedDuringSolve": None,
                    "gil": None,
                    "largeDocument": None,
                    "scoresSolve": None,
                },
                "interpreterPoolImportError": None,
            }
        ),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "process-host",
            "--console-package-probe",
            "--output",
            str(output),
            "--scores-solve-tree",
            str(tree),
        ],
    )

    assert main() == 0
    assert seen == [tree]
