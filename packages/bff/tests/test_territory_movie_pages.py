"""Territory movie pages are ordinary HTML responses, not blob URLs."""

import pytest
from bff.app import app
from bff.territory_movie_pages import TERRITORY_MOVIE_PAGE_CSP, territory_movie_pages
from fastapi.testclient import TestClient

client = TestClient(app)

DOCUMENT = "<!DOCTYPE html><html><body>Territory movie</body></html>"


@pytest.fixture(autouse=True)
def _clear_pages():
    territory_movie_pages.clear()
    yield
    territory_movie_pages.clear()


def test_serves_the_posted_document_until_it_is_discarded():
    created = client.post(
        "/territory-movie-pages",
        content=DOCUMENT,
        headers={"Content-Type": "text/html; charset=utf-8"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["path"] == f"/bff/territory-movie-pages/{body['id']}"

    served = client.get(f"/territory-movie-pages/{body['id']}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("text/html")
    assert served.headers["content-security-policy"] == TERRITORY_MOVIE_PAGE_CSP
    assert served.text == DOCUMENT

    deleted = client.delete(f"/territory-movie-pages/{body['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/territory-movie-pages/{body['id']}").status_code == 404


def test_rejects_a_body_that_is_not_the_movie_document():
    response = client.post("/territory-movie-pages", content="not html")
    assert response.status_code == 422


def test_missing_page_is_not_found_and_delete_is_idempotent():
    missing = "a" * 32
    assert client.get(f"/territory-movie-pages/{missing}").status_code == 404
    assert client.delete(f"/territory-movie-pages/{missing}").status_code == 204
    assert client.get("/territory-movie-pages/not-an-id").status_code == 404
