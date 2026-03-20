"""Games list for the console shell: stored game ids from the Core store (shallow read).

This router is mounted on the BFF sub-app at prefix `/games`, so **GET /games** is the path
when using `TestClient(bff.app)` or OpenAPI for the BFF app alone. The root server mounts the
BFF under `/bff`, so the SPA and full-stack docs use **GET /bff/games**.

The handler maps Core store path `games` shallow children to `{"games": [{"id": "..."}]}`.
If `games` does not exist (`NotFoundError` from the store), returns an empty list.
"""

from api.errors import NotFoundError
from api.services.store_service import StoreService
from api.storage import get_storage
from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_stored_games():
    """Return game ids present under store path `games` (next-hop segment names).

    Route: **GET /games** on the BFF app; **GET /bff/games** when the BFF is mounted at `/bff`.

    Uses the same shallow enumeration as GET /api/v1/store/games?view=shallow.
    """
    svc = StoreService(get_storage())
    try:
        shallow = svc.read_shallow("games")
    except NotFoundError:
        return {"games": []}
    children = shallow.get("children") or []
    return {"games": [{"id": str(child)} for child in children]}
