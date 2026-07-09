"""BFF sub-app: SPA-shaped endpoints, no business logic."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel

from bff.config import get_config
from bff.errors import BFFError, BFFValidationError, make_http_exception_handler
from bff.routers import analytics, diagnostics, diagnostics_compute, games, shell
from bff.strip_bff_prefix import StripBffPrefixWhenRootApp
from bff.transport.fleet_table_stream_responses import (
    FleetTableStreamCompleteEvent,
    FleetTableStreamErrorEvent,
    FleetTableStreamLedgerUpdatedEvent,
    FleetTableStreamProvenanceEvent,
    FleetTableStreamRecordRefinedEvent,
)
from bff.transport.game_responses import (
    LoadAllProgressUpdate,
    LoadAllStreamCompleteEvent,
    LoadAllStreamErrorEvent,
    LoadAllStreamProgressEvent,
)
from bff.transport.inference_stream_responses import (
    InferenceStreamCompleteEvent,
    InferenceStreamErrorEvent,
    InferenceStreamProgressEvent,
    InferenceStreamSolutionEvent,
)

app = FastAPI(
    title="Planets Console BFF",
    openapi_url="/openapi.json",
)


def _merge_model_json_schema(openapi_schema: dict, model: type[BaseModel]) -> None:
    """Add ``model`` and any nested ``$defs`` to OpenAPI components (for manual ``$ref`` use)."""
    raw = model.model_json_schema(ref_template="#/components/schemas/{model}")
    nested = raw.pop("$defs", {})
    schemas = openapi_schema.setdefault("components", {}).setdefault("schemas", {})
    schemas[model.__name__] = raw
    for name, definition in nested.items():
        schemas.setdefault(name, definition)


def build_openapi_schema() -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    for model in (
        LoadAllProgressUpdate,
        LoadAllStreamProgressEvent,
        LoadAllStreamCompleteEvent,
        LoadAllStreamErrorEvent,
        InferenceStreamSolutionEvent,
        InferenceStreamProgressEvent,
        InferenceStreamCompleteEvent,
        InferenceStreamErrorEvent,
        FleetTableStreamLedgerUpdatedEvent,
        FleetTableStreamRecordRefinedEvent,
        FleetTableStreamProvenanceEvent,
        FleetTableStreamCompleteEvent,
        FleetTableStreamErrorEvent,
    ):
        _merge_model_json_schema(openapi_schema, model)
    app.openapi_schema = openapi_schema
    return openapi_schema


app.openapi = build_openapi_schema  # type: ignore[method-assign]
# CORS origins come from BFF config (set by server from amalgamated config)
_origins = list(get_config().cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Standalone `uvicorn bff.app:app` receives the same `/bff/...` paths as the browser sends;
# strip the prefix so routes match. When the root server mounts this app at `/bff`, Starlette
# already strips the mount prefix, so this no-ops.
app.add_middleware(StripBffPrefixWhenRootApp)
app.add_exception_handler(Exception, make_http_exception_handler(BFFError))
# Explicit handler so Starlette/FastAPI invokes it for sync route endpoints (see api/app.py).
app.add_exception_handler(BFFValidationError, make_http_exception_handler(BFFValidationError))
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"])
app.include_router(diagnostics_compute.router, prefix="/diagnostics", tags=["diagnostics"])
app.include_router(games.router, prefix="/games", tags=["games"])
app.include_router(shell.router, prefix="/shell", tags=["shell"])


@app.get("/health")
def health():
    return {"status": "ok", "layer": "bff"}
