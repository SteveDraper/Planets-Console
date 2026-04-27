"""BFF sub-app: SPA-shaped endpoints, no business logic."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from bff.config import get_config
from bff.errors import BFFError, make_http_exception_handler
from bff.routers import analytics, diagnostics, games, shell
from bff.strip_bff_prefix import StripBffPrefixWhenRootApp

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
# Standalone `uvicorn bff.app:app` receives the same `/bff/...` paths as the browser sends;
# strip the prefix so routes match. When the root server mounts this app at `/bff`, Starlette
# already strips the mount prefix, so this no-ops.
app.add_middleware(StripBffPrefixWhenRootApp)
app.add_exception_handler(Exception, make_http_exception_handler(BFFError))
app.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
app.include_router(diagnostics.router, prefix="/diagnostics", tags=["diagnostics"])
app.include_router(games.router, prefix="/games", tags=["games"])
app.include_router(shell.router, prefix="/shell", tags=["shell"])


@app.get("/health")
def health():
    return {"status": "ok", "layer": "bff"}
