"""Built SPA static files must use browser-accepted script types."""

from __future__ import annotations

import mimetypes

import pytest
from api.config import ApiConfig
from api.config import set_config as set_api_config
from api.storage_factory import clear_backend_cache
from fastapi.testclient import TestClient


@pytest.fixture
def _api_config_and_storage():
    clear_backend_cache()
    set_api_config(
        ApiConfig(
            storage_backend="ephemeral",
            storage_asset_path=None,
            include_dummy_data=False,
        )
    )
    yield
    clear_backend_cache()


def test_js_assets_stay_javascript_when_platform_maps_js_to_text_plain(
    _api_config_and_storage, tmp_path, monkeypatch
):
    """Windows registry Content Type for .js is text/plain; module scripts need JavaScript."""
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    script = "export {}\n"
    stylesheet = "body{}\n"
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    for name in ("index-abc.js", "index-abc.mjs"):
        (assets / name).write_text(script, encoding="utf-8")
    (assets / "index-abc.css").write_text(stylesheet, encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST", str(dist))

    previous = {suffix: mimetypes.guess_type(f"module{suffix}")[0] for suffix in (".js", ".mjs")}
    for suffix in previous:
        mimetypes.add_type("text/plain", suffix)
    try:
        from server.app import create_app

        with TestClient(create_app(), base_url="http://127.0.0.1:8000") as client:
            for name in ("index-abc.js", "index-abc.mjs"):
                response = client.get(f"/assets/{name}")
                media_type = response.headers["content-type"].split(";", 1)[0].strip()
                assert response.status_code == 200
                assert response.text == script
                assert media_type == "text/javascript"
            stylesheet_response = client.get("/assets/index-abc.css")
            stylesheet_type = stylesheet_response.headers["content-type"].split(";", 1)[0].strip()
            assert stylesheet_response.status_code == 200
            assert stylesheet_response.text == stylesheet
            assert stylesheet_type == "text/css"
    finally:
        for suffix, media_type in previous.items():
            if media_type is not None:
                mimetypes.add_type(media_type, suffix)
