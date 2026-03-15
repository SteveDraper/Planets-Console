"""Store CRUD REST API: Create (PUT), Read (GET), Update (POST), Delete (DELETE)."""
from typing import Any

from fastapi import APIRouter, Body, Depends, Query
from starlette.responses import Response

from api.errors import ValidationError
from api.services.store_service import StoreService
from api.storage import get_storage
from api.storage.base import StorageBackend

router = APIRouter(prefix="/v1/store", tags=["store"])


def get_store_service(storage: StorageBackend = Depends(get_storage)) -> StoreService:
    return StoreService(storage)


def _ensure_json_value(raw: Any) -> Any:
    """Accept only JSON-serializable types; return as-is for store layer."""
    if raw is None or isinstance(raw, (bool, int, float, str)):
        return raw
    if isinstance(raw, dict):
        return {k: _ensure_json_value(v) for k, v in raw.items()}
    if isinstance(raw, list):
        return [_ensure_json_value(v) for v in raw]
    raise ValidationError("Request body must be JSON-serializable (dict, list, str, int, float, bool, null)")


@router.put("/{path:path}", status_code=201)
def create(
    path: str,
    body: Any = Body(...),
    svc: StoreService = Depends(get_store_service),
) -> Any:
    """Create a node at path. Path must not exist. Ancestor objects are created as needed."""
    value = _ensure_json_value(body)
    svc.create(path, value)
    return value


@router.get("/{path:path}")
def read(
    path: str,
    view: str = Query("full", description="full | shallow"),
    svc: StoreService = Depends(get_store_service),
):
    """Read node at path. view=full returns the node; view=shallow returns metadata and children."""
    if view == "full":
        return svc.read(path)
    if view == "shallow":
        return svc.read_shallow(path)
    raise ValidationError(f"Invalid view: {view!r} (expected 'full' or 'shallow')")


@router.post("/{path:path}")
def update(
    path: str,
    body: Any = Body(...),
    merge: str | None = Query(None, description="For arrays: append | prepend"),
    svc: StoreService = Depends(get_store_service),
):
    """Update node at path (additive merge for objects; replace/append/prepend for arrays)."""
    value = _ensure_json_value(body)
    merge_array = None
    if merge is not None:
        if merge not in ("append", "prepend"):
            raise ValidationError(f"Invalid merge: {merge!r} (expected 'append' or 'prepend')")
        merge_array = merge
    return svc.update(path, value, merge_array=merge_array)


@router.delete("/{path:path}", status_code=204)
def delete(
    path: str,
    svc: StoreService = Depends(get_store_service),
) -> Response:
    """Delete the node at path."""
    svc.delete(path)
    return Response(status_code=204)
