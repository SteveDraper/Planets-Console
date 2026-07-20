#!/usr/bin/env python3
"""
Subset a full BFF OpenAPI JSON dump into per-slice documents for frontend codegen.

Each slice aligns with a BFF router mount (games, analytics, shell, diagnostics, credentials).
Paths are selected by prefix; ``/health`` is included in the shell slice only.
Each output document embeds the full transitive ``#/components/schemas/*`` closure
for its paths (duplicate shared schemas across slices is intentional).

Usage:
  uv run python scripts/filter_bff_openapi.py INPUT.json OUTPUT_DIR
  uv run python scripts/filter_bff_openapi.py \\
      .bff-openapi.json packages/frontend/.bff-openapi-slices
"""

from __future__ import annotations

import copy
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typer

SCHEMA_REF_PREFIX = "#/components/schemas/"

# v1 slices: one JSON file per key, aligned with BFF router mounts in bff.app.
SLICE_PATH_PREFIXES: dict[str, tuple[str, ...]] = {
    "games": ("/games",),
    "analytics": ("/analytics",),
    "shell": ("/shell", "/health"),
    "diagnostics": ("/diagnostics",),
    "credentials": ("/credentials",),
}

app = typer.Typer(add_completion=False, no_args_is_help=True)


def path_matches_slice(path: str, prefixes: tuple[str, ...]) -> bool:
    """Return True when ``path`` belongs to a slice prefix (exact ``/health`` for shell)."""
    for prefix in prefixes:
        if prefix == "/health":
            if path == "/health":
                return True
        elif path == prefix or path.startswith(f"{prefix}/"):
            return True
    return False


def iter_schema_ref_names(obj: Any) -> set[str]:
    """Collect schema names from ``#/components/schemas/{name}`` refs in a JSON tree."""
    found: set[str] = set()
    if isinstance(obj, dict):
        ref = obj.get("$ref")
        if isinstance(ref, str) and ref.startswith(SCHEMA_REF_PREFIX):
            found.add(ref.removeprefix(SCHEMA_REF_PREFIX))
        for value in obj.values():
            found |= iter_schema_ref_names(value)
    elif isinstance(obj, list):
        for item in obj:
            found |= iter_schema_ref_names(item)
    return found


def transitive_schema_closure(schemas: Mapping[str, Any], root_names: set[str]) -> set[str]:
    """Expand ``root_names`` to every schema reachable via nested ``$ref`` links."""
    closure = set(root_names)
    pending = list(root_names)
    while pending:
        name = pending.pop()
        schema = schemas.get(name)
        if schema is None:
            continue
        for ref_name in iter_schema_ref_names(schema):
            if ref_name not in closure:
                closure.add(ref_name)
                pending.append(ref_name)
    return closure


def filter_openapi_slice(full: dict[str, Any], slice_name: str) -> dict[str, Any]:
    """Build one slice document: matching paths plus transitive schema closure."""
    if slice_name not in SLICE_PATH_PREFIXES:
        msg = f"Unknown slice {slice_name!r}; expected one of {sorted(SLICE_PATH_PREFIXES)}"
        raise ValueError(msg)

    prefixes = SLICE_PATH_PREFIXES[slice_name]
    all_paths = full.get("paths", {})
    filtered_paths = {
        path: copy.deepcopy(spec)
        for path, spec in all_paths.items()
        if path_matches_slice(path, prefixes)
    }

    full_schemas = full.get("components", {}).get("schemas", {})
    needed_schema_names = transitive_schema_closure(
        full_schemas,
        iter_schema_ref_names(filtered_paths),
    )
    filtered_schemas = {
        name: copy.deepcopy(full_schemas[name])
        for name in sorted(needed_schema_names)
        if name in full_schemas
    }

    result: dict[str, Any] = {
        "openapi": full.get("openapi", "3.1.0"),
        "info": copy.deepcopy(full.get("info", {})),
        "paths": filtered_paths,
    }
    if "servers" in full:
        result["servers"] = copy.deepcopy(full["servers"])
    if filtered_schemas:
        result["components"] = {"schemas": filtered_schemas}
    return result


def filter_bff_openapi(full: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return all v1 slice documents keyed by slice name."""
    return {name: filter_openapi_slice(full, name) for name in SLICE_PATH_PREFIXES}


def write_slice_documents(full: dict[str, Any], output_dir: Path) -> list[Path]:
    """Write ``{slice}.json`` files under ``output_dir``; return written paths."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for slice_name, document in filter_bff_openapi(full).items():
        path = output_dir / f"{slice_name}.json"
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


@app.command()
def main(
    input_path: Path = typer.Argument(..., help="Full BFF OpenAPI JSON dump"),
    output_dir: Path = typer.Argument(..., help="Directory for per-slice JSON files"),
) -> None:
    """Filter a BFF OpenAPI dump into v1 codegen slice documents."""
    try:
        full = json.loads(input_path.read_text(encoding="utf-8"))
    except OSError as exc:
        typer.echo(f"Error reading {input_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except json.JSONDecodeError as exc:
        typer.echo(f"Error parsing {input_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not isinstance(full, dict):
        typer.echo(f"Expected JSON object in {input_path}", err=True)
        raise typer.Exit(code=1)

    written = write_slice_documents(full, output_dir)
    for path in written:
        typer.echo(path)


if __name__ == "__main__":
    try:
        app()
    except typer.Exit as exc:
        sys.exit(exc.exit_code)
