"""BFF sub-app: SPA-shaped endpoints, no business logic."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bff.routers import analytics

app = FastAPI(
    title="Planets Console BFF",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])


@app.get("/health")
def health():
    return {"status": "ok", "layer": "bff"}
