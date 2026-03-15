"""Minimal Core REST API sub-app. Stub until real domain exists."""
from fastapi import FastAPI

from api.errors import (
    ConflictError,
    CoreAPIError,
    NotFoundError,
    ValidationError,
    make_http_exception_handler,
)
from api.routers import store

app = FastAPI(
    title="Planets Console Core API",
    openapi_url="/openapi.json",
)
# Generic handler for all CoreAPIError subclasses (404, 409, 422, etc.)
app.add_exception_handler(Exception, make_http_exception_handler(CoreAPIError))
# Explicit handlers so Starlette/FastAPI invokes them when exceptions are raised from sync endpoints
for _exc_cls in (NotFoundError, ConflictError, ValidationError):
    app.add_exception_handler(_exc_cls, make_http_exception_handler(CoreAPIError))
app.include_router(store.router)


@app.get("/health")
def health():
    return {"status": "ok", "layer": "api"}
