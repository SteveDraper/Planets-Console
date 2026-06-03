"""Fail if the monolithic frontend BFF schema file reappears."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MONOLITHIC_SCHEMA_REL = Path("packages/frontend/src/api/schema.ts")
MONOLITHIC_SCHEMA = REPO_ROOT / MONOLITHIC_SCHEMA_REL


def main() -> int:
    if MONOLITHIC_SCHEMA.is_file():
        print(
            f"ERROR: monolithic {MONOLITHIC_SCHEMA_REL.as_posix()} must not exist; "
            "use schema-<slice>.ts only "
            "(see docs/adr/0003-frontend-bff-contract-codegen.md).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
