"""Minimal Core REST API sub-app. Stub until real domain exists."""
from fastapi import FastAPI

app = FastAPI(
    title="Planets Console Core API",
    openapi_url="/openapi.json",
)


@app.get("/health")
def health():
    return {"status": "ok", "layer": "api"}
