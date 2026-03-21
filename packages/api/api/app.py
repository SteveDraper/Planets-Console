"""Core REST API sub-app: data model, business logic, and domain routes."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.config import get_config
from api.errors import (
    ConflictError,
    CoreAPIError,
    LoginCredentialsRequiredError,
    NotFoundError,
    UpstreamPlanetsError,
    ValidationError,
    make_http_exception_handler,
)
from api.routers import games, store
from api.services.seed import seed_dummy_data
from api.storage import get_storage


@asynccontextmanager
async def _lifespan(app: FastAPI):
    if get_config().include_dummy_data:
        seed_dummy_data(get_storage())
    yield


app = FastAPI(
    title="Planets Console Core API",
    openapi_url="/openapi.json",
    lifespan=_lifespan,
)
# Generic handler for all CoreAPIError subclasses (404, 409, 422, etc.)
app.add_exception_handler(Exception, make_http_exception_handler(CoreAPIError))
# Explicit handlers so Starlette/FastAPI invokes them when exceptions are raised from sync endpoints
for _exc_cls in (
    NotFoundError,
    ConflictError,
    ValidationError,
    LoginCredentialsRequiredError,
    UpstreamPlanetsError,
):
    app.add_exception_handler(_exc_cls, make_http_exception_handler(CoreAPIError))
app.include_router(store.router)
app.include_router(games.router)


@app.get("/health")
def health():
    return {"status": "ok", "layer": "api"}
