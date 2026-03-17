"""Root FastAPI app: mounts Core API under /api and BFF under /bff.

In non-dev deployments you can serve the built frontend from this process:
set FRONTEND_DIST to the path to the frontend dist/ (e.g. packages/frontend/dist),
or run with that directory present; the app will serve static assets and SPA fallback.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from api.app import app as api_app
from bff.app import app as bff_app
from fastapi import FastAPI
from fastapi.responses import FileResponse
from starlette.staticfiles import StaticFiles


def _frontend_dist() -> Path | None:
    path = os.environ.get("FRONTEND_DIST")
    if path:
        p = Path(path)
    else:
        # Default: packages/frontend/dist relative to cwd (monorepo)
        p = Path("packages/frontend/dist")
    return p if p.is_dir() else None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Shared startup/shutdown when needed
    yield


app = FastAPI(
    title="Planets Console",
    lifespan=lifespan,
)
app.mount("/api", api_app)
app.mount("/bff", bff_app)


@app.get("/health")
def health():
    return {"status": "ok"}


# Optional: serve built frontend for single-server deployment
_frontend = _frontend_dist()
if _frontend is not None:
    _assets = _frontend / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    _index = _frontend / "index.html"
    if _index.is_file():

        @app.get("/")
        def _serve_index():
            return FileResponse(str(_index))

        @app.get("/{full_path:path}")
        def _spa_fallback(full_path: str):
            return FileResponse(str(_index))
