"""Tests for :mod:`filter_bff_openapi` path filtering and ``$ref`` closure."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from filter_bff_openapi import (
    SLICE_PATH_PREFIXES,
    filter_bff_openapi,
    filter_openapi_slice,
    iter_schema_ref_names,
    path_matches_slice,
    transitive_schema_closure,
    write_slice_documents,
)


def _minimal_openapi(*, paths: dict, schemas: dict | None = None) -> dict:
    doc: dict = {
        "openapi": "3.1.0",
        "info": {"title": "Test BFF", "version": "0.0.0"},
        "paths": paths,
    }
    if schemas is not None:
        doc["components"] = {"schemas": schemas}
    return doc


@pytest.mark.parametrize(
    ("path", "slice_name", "expected"),
    [
        ("/games", "games", True),
        ("/games/1/info", "games", True),
        ("/gamesmanship", "games", False),
        ("/analytics", "analytics", True),
        ("/analytics/foo/table", "analytics", True),
        ("/analytic", "analytics", False),
        ("/shell/bootstrap", "shell", True),
        ("/shell", "shell", True),
        ("/health", "shell", True),
        ("/health/extra", "shell", False),
        ("/diagnostics/recent", "diagnostics", True),
        ("/diagnostics", "diagnostics", True),
        ("/diagnostic", "diagnostics", False),
        ("/games", "analytics", False),
        ("/health", "games", False),
    ],
)
def test_path_matches_slice(path: str, slice_name: str, expected: bool) -> None:
    prefixes = SLICE_PATH_PREFIXES[slice_name]
    assert path_matches_slice(path, prefixes) is expected


def test_transitive_schema_closure_includes_nested_refs() -> None:
    schemas = {
        "Root": {"$ref": "#/components/schemas/Middle"},
        "Middle": {
            "properties": {
                "leaf": {"$ref": "#/components/schemas/Leaf"},
            }
        },
        "Leaf": {"type": "string"},
        "Unrelated": {"type": "integer"},
    }
    closure = transitive_schema_closure(schemas, {"Root"})
    assert closure == {"Root", "Middle", "Leaf"}


def test_filter_slice_keeps_only_prefix_paths_and_reachable_schemas() -> None:
    full = _minimal_openapi(
        paths={
            "/games": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/GameList"},
                                }
                            }
                        },
                        "422": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/HTTPValidationError"},
                                }
                            }
                        },
                    }
                }
            },
            "/analytics": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/health": {"get": {"responses": {"200": {"description": "ok"}}}},
        },
        schemas={
            "GameList": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/GameItem"},
            },
            "GameItem": {"type": "object"},
            "HTTPValidationError": {
                "properties": {
                    "detail": {
                        "items": {"$ref": "#/components/schemas/ValidationError"},
                    }
                }
            },
            "ValidationError": {"type": "object"},
            "AnalyticsOnly": {"type": "string"},
        },
    )

    games = filter_openapi_slice(full, "games")

    assert set(games["paths"]) == {"/games"}
    schema_names = set(games["components"]["schemas"])
    assert schema_names == {
        "GameList",
        "GameItem",
        "HTTPValidationError",
        "ValidationError",
    }
    assert "AnalyticsOnly" not in schema_names


def test_shell_slice_includes_health_and_shell_paths() -> None:
    full = _minimal_openapi(
        paths={
            "/shell/bootstrap": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/ShellBootstrap"},
                                }
                            }
                        }
                    }
                }
            },
            "/health": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/games": {"get": {"responses": {"200": {"description": "ok"}}}},
        },
        schemas={
            "ShellBootstrap": {"type": "object"},
            "GameOnly": {"type": "object"},
        },
    )

    shell = filter_openapi_slice(full, "shell")

    assert set(shell["paths"]) == {"/shell/bootstrap", "/health"}
    assert set(shell["components"]["schemas"]) == {"ShellBootstrap"}


def test_shared_schemas_duplicated_across_slices() -> None:
    full = _minimal_openapi(
        paths={
            "/games": {
                "get": {
                    "responses": {
                        "422": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/HTTPValidationError"},
                                }
                            }
                        }
                    }
                }
            },
            "/analytics": {
                "get": {
                    "responses": {
                        "422": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/HTTPValidationError"},
                                }
                            }
                        }
                    }
                }
            },
        },
        schemas={
            "HTTPValidationError": {
                "properties": {
                    "detail": {
                        "items": {"$ref": "#/components/schemas/ValidationError"},
                    }
                }
            },
            "ValidationError": {"type": "object"},
        },
    )

    games = filter_openapi_slice(full, "games")
    analytics = filter_openapi_slice(full, "analytics")

    assert set(games["components"]["schemas"]) == {"HTTPValidationError", "ValidationError"}
    assert set(analytics["components"]["schemas"]) == {"HTTPValidationError", "ValidationError"}


def test_filter_bff_openapi_emits_all_v1_slices() -> None:
    full = _minimal_openapi(
        paths={
            "/games": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/analytics": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/shell/bootstrap": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/health": {"get": {"responses": {"200": {"description": "ok"}}}},
            "/diagnostics/recent": {"get": {"responses": {"200": {"description": "ok"}}}},
        },
    )

    slices = filter_bff_openapi(full)

    assert set(slices) == set(SLICE_PATH_PREFIXES)
    assert set(slices["games"]["paths"]) == {"/games"}
    assert set(slices["analytics"]["paths"]) == {"/analytics"}
    assert set(slices["shell"]["paths"]) == {"/shell/bootstrap", "/health"}
    assert set(slices["diagnostics"]["paths"]) == {"/diagnostics/recent"}


def test_write_slice_documents_creates_json_files(tmp_path: Path) -> None:
    full = _minimal_openapi(
        paths={"/health": {"get": {"responses": {"200": {"description": "ok"}}}}},
    )

    written = write_slice_documents(full, tmp_path)

    assert len(written) == len(SLICE_PATH_PREFIXES)
    for path in written:
        assert path.parent == tmp_path
        assert path.suffix == ".json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "paths" in payload
        assert payload["info"]["title"] == "Test BFF"


def test_real_bff_openapi_slices_have_closed_refs() -> None:
    pytest.importorskip("bff")
    from bff.app import app

    full = app.openapi()
    slices = filter_bff_openapi(full)

    assert set(slices["games"]["paths"]) == {
        path for path in full["paths"] if path == "/games" or path.startswith("/games/")
    }
    assert set(slices["analytics"]["paths"]) == {
        path for path in full["paths"] if path == "/analytics" or path.startswith("/analytics/")
    }
    assert set(slices["shell"]["paths"]) == {
        path for path in full["paths"] if path == "/shell" or path.startswith("/shell/")
    } | {"/health"}
    assert set(slices["diagnostics"]["paths"]) == {
        path for path in full["paths"] if path == "/diagnostics" or path.startswith("/diagnostics/")
    }

    full_schemas = full.get("components", {}).get("schemas", {})
    for slice_name, document in slices.items():
        path_refs = iter_schema_ref_names(document["paths"])
        included = set(document.get("components", {}).get("schemas", {}))
        expected = transitive_schema_closure(full_schemas, path_refs)
        assert expected <= included, f"{slice_name} missing schema closure: {expected - included}"


def test_iter_schema_ref_names_ignores_non_schema_refs() -> None:
    tree = {
        "a": {"$ref": "#/components/schemas/Foo"},
        "b": {"$ref": "#/components/responses/NotIncluded"},
    }
    assert iter_schema_ref_names(tree) == {"Foo"}
