"""Serve a Territory movie document at an http address the browser can save."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response

from bff.errors import BFFValidationError
from bff.territory_movie_pages import (
    TERRITORY_MOVIE_PAGE_CSP,
    territory_movie_page_path,
    territory_movie_pages,
)

router = APIRouter()

_PAGE_HEADERS = {
    "Content-Security-Policy": TERRITORY_MOVIE_PAGE_CSP,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


@router.post("/territory-movie-pages", status_code=201)
async def create_territory_movie_page(request: Request) -> dict[str, str]:
    raw = await request.body()
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BFFValidationError("Territory movie page must be UTF-8 HTML.") from exc
    page_id = territory_movie_pages.put(html)
    return {"id": page_id, "path": territory_movie_page_path(page_id)}


@router.get("/territory-movie-pages/{page_id}")
async def read_territory_movie_page(page_id: str) -> HTMLResponse:
    html = territory_movie_pages.get(page_id)
    return HTMLResponse(content=html, headers=_PAGE_HEADERS)


@router.delete("/territory-movie-pages/{page_id}", status_code=204)
async def delete_territory_movie_page(page_id: str) -> Response:
    territory_movie_pages.discard(page_id)
    return Response(status_code=204)
