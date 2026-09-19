# ADR 0027 addendum: packaged SAT workers are a sibling binary

Status: accepted (addendum to [ADR 0027](0027-console-package-bundler-and-process-host.md))

## Context

macOS cannot fork an AppKit parent. PyInstaller children of the windowed process-host executable typically re-exec the full freeze. Eight GUI copies after a long scores session are unacceptable (venv `run_scores_tier_solve` idle RSS is already ~135 MB; a packaged `.app` clone is worse).

[#502](https://github.com/SteveDraper/Planets-Console/issues/502) showed venv process SAT recovers occupancy (stay-wire ~1x, stay-long ~1x, ~7 cores while full) with ortools-scale idle RSS, not `create_app` x 8. That isolation is only shippable in the console package if spawn does not clone the process host.

## Decision

Packaged SAT / process-pool workers are a **sibling `sat_worker` executable** collected into the same onedir / `.app` as the process host (macOS `Contents/MacOS/sat_worker`, Windows `sat_worker.exe`). The process host calls `multiprocessing.set_executable` to that path before constructing `ProcessPoolExecutor`.

Not chosen: a long-lived solver daemon with a second IPC protocol. Phase 1 already pickles a storage-rebuild job wire into `ProcessPoolExecutor`; keep that plane.

The worker entry (`api.compute.sat_worker_entry`) imports solver, file storage, and the scores `tier_solve` job-wire codec only. It does not import AppKit, FastAPI `create_app`, or `server.process_host`. Freeze dests still must not collect the **console data directory**; the worker reads `storageRoot` from the job wire.

Scores `tier_solve` remains declared `thread` with process as occupancy / test opt-in. Process SAT is not the production default.

## Consequences

- A frozen `ProcessPoolExecutor` must not spawn `sys.executable` of the GUI. Missing `sat_worker` fails loud rather than cloning the `.app`.
- The installer wrapper copies the whole onedir / `.app`, so the sibling binary is included without a second wrap rule.
- Tracked by [#503](https://github.com/SteveDraper/Planets-Console/issues/503) (series [#500](https://github.com/SteveDraper/Planets-Console/issues/500)). Packaged occupancy measurement is [#504](https://github.com/SteveDraper/Planets-Console/issues/504).
