"""HTTP client for Planets.nu public API (login, load game info)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from api.config import get_config
from api.errors import UpstreamPlanetsError, ValidationError

logger = logging.getLogger(__name__)


def _safe_httpx_error_summary(exc: httpx.HTTPError) -> str:
    """Describe an httpx error without str(exc); httpx often embeds full URLs with query params."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.request.method} {exc.request.url.path} -> HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return f"{exc.request.method} {exc.request.url.path}: {type(exc).__name__}"
    return type(exc).__name__


class PlanetsNuClient:
    """Thin wrapper around api.planets.nu for login, loadinfo, and loadturn."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    @classmethod
    def from_config(cls) -> PlanetsNuClient:
        return cls(get_config().planets_api_base_url)

    def login(self, username: str, password: str) -> str:
        url = f"{self._base_url}/login"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, params={"username": username, "password": password})
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Planets.nu login HTTP error: %s", _safe_httpx_error_summary(exc))
            raise UpstreamPlanetsError("Planets.nu login request failed.") from exc
        except ValueError as exc:
            raise UpstreamPlanetsError("Planets.nu login returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise UpstreamPlanetsError("Planets.nu login returned an unexpected payload.")
        if not data.get("success"):
            detail = data.get("error") or data.get("message") or "Login was not successful."
            raise ValidationError(str(detail))
        api_key = data.get("apikey")
        if not api_key or not isinstance(api_key, str):
            raise UpstreamPlanetsError("Planets.nu login response did not include an api key.")
        return api_key

    def load_game_info(self, game_id: int) -> dict[str, Any]:
        url = f"{self._base_url}/game/loadinfo"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, params={"gameid": game_id})
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Planets.nu loadinfo HTTP error: %s", _safe_httpx_error_summary(exc))
            raise UpstreamPlanetsError("Planets.nu load game info request failed.") from exc
        except ValueError as exc:
            raise UpstreamPlanetsError("Planets.nu loadinfo returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise UpstreamPlanetsError("Planets.nu loadinfo returned an unexpected payload.")
        return data

    def load_turn(
        self,
        *,
        game_id: int,
        turn: int,
        player_id: int,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """GET /game/loadturn; returns the full JSON body (success, rst, ...)."""
        url = f"{self._base_url}/game/loadturn"
        params: dict[str, Any] = {
            "gameid": game_id,
            "turn": turn,
            "playerid": player_id,
        }
        if api_key:
            params["apikey"] = api_key
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Planets.nu loadturn HTTP error: %s", _safe_httpx_error_summary(exc))
            raise UpstreamPlanetsError("Planets.nu load turn request failed.") from exc
        except ValueError as exc:
            raise UpstreamPlanetsError("Planets.nu loadturn returned invalid JSON.") from exc

        if not isinstance(data, dict):
            raise UpstreamPlanetsError("Planets.nu loadturn returned an unexpected payload.")
        return data
