"""Minimal Core REST API sub-app. Stub until real domain exists."""
from fastapi import FastAPI

from api.errors import CoreAPIError, make_http_exception_handler

app = FastAPI(
    title="Planets Console Core API",
    openapi_url="/openapi.json",
)
app.add_exception_handler(Exception, make_http_exception_handler(CoreAPIError))


@app.get("/health")
def health():
    return {"status": "ok", "layer": "api"}
