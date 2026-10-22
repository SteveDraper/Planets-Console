"""Ephemeral Territory movie documents served so the browser can save the page.

The SPA builds the HTML. This store only holds that text until the movie window closes.
"""

from uuid import uuid4

from bff.errors import BFFNotFoundError, BFFValidationError

_PAGE_ID_LENGTH = 32


def _is_page_id(page_id: str) -> bool:
    if len(page_id) != _PAGE_ID_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in page_id)


class TerritoryMoviePageStore:
    def __init__(self) -> None:
        self._pages: dict[str, str] = {}

    def put(self, html: str) -> str:
        document = html.lstrip()
        if document == "":
            raise BFFValidationError("Territory movie page is empty.")
        if not document.startswith("<!DOCTYPE html>"):
            raise BFFValidationError("Territory movie page must be an HTML document.")
        page_id = uuid4().hex
        self._pages[page_id] = document
        return page_id

    def get(self, page_id: str) -> str:
        if not _is_page_id(page_id):
            raise BFFNotFoundError(f"Territory movie page not found: {page_id}")
        try:
            return self._pages[page_id]
        except KeyError as exc:
            raise BFFNotFoundError(f"Territory movie page not found: {page_id}") from exc

    def discard(self, page_id: str) -> None:
        self._pages.pop(page_id, None)

    def clear(self) -> None:
        self._pages.clear()


territory_movie_pages = TerritoryMoviePageStore()

# Unique origin so the stored document cannot call the console API. Scripts still run.
TERRITORY_MOVIE_PAGE_CSP = "sandbox allow-scripts"


def territory_movie_page_path(page_id: str) -> str:
    return f"/bff/territory-movie-pages/{page_id}"
