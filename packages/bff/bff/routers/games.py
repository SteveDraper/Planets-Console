"""Games list for the console shell: stored game ids from the Core store (shallow read).

GET /bff/games maps Core store path `games` shallow children to `{ "games": [ { "id": "..." } ] }`.
If `games` does not exist (404 from store), returns an empty list.
"""

from api.errors import NotFoundError
from api.services.store_service import StoreService
from api.storage import get_storage
from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_stored_games():
    """Return game ids present under store path `games` (next-hop segment names).

    Uses the same shallow enumeration as GET /api/v1/store/games?view=shallow.
    """
    svc = StoreService(get_storage())
    try:
        shallow = svc.read_shallow("games")
    except NotFoundError:
        return {"games": []}
    children = shallow.get("children") or []
    return {"games": [{"id": str(child)} for child in children]}
