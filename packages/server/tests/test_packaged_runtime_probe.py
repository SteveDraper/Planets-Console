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
    assert not (tmp_path / "Application Support").exists()
