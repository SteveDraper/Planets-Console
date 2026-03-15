"""BFF sub-app: SPA-shaped endpoints, no business logic."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bff.config import get_config
from bff.errors import BFFError, make_http_exception_handler
from bff.routers import analytics

app = FastAPI(
    title="Planets Console BFF",
    openapi_url="/openapi.json",
)
# CORS origins come from BFF config (set by server from amalgamated config)
_origins = list(get_config().cors_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_exception_handler(Exception, make_http_exception_handler(BFFError))
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])


@app.get("/health")
def health():
    return {"status": "ok", "layer": "bff"}
