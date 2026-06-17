"""HTTP client for Planets.nu public API (login, load game info)."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

import httpx

from api.config import get_config
from api.errors import UpstreamPlanetsError, ValidationError

logger = logging.getLogger(__name__)

_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_BACKOFF_SECONDS = 2.0


def _safe_httpx_error_summary(exc: httpx.HTTPError) -> str:
    """Describe an httpx error without str(exc); httpx often embeds full URLs with query params."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.request.method} {exc.request.url.path} -> HTTP {exc.response.status_code}"
    if isinstance(exc, httpx.RequestError):
        return f"{exc.request.method} {exc.request.url.path}: {type(exc).__name__}"
    return type(exc).__name__


def _is_transient_request_error(exc: httpx.HTTPError) -> bool:
    """True for transport-layer failures that may succeed on retry."""
    return isinstance(exc, httpx.RequestError) and not isinstance(exc, httpx.HTTPStatusError)


class PlanetsNuClient:
    """Thin wrapper around api.planets.nu for login, loadinfo, and loadturn."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 60.0,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: float = _DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_attempts = max(1, max_attempts)
        self._retry_backoff_seconds = retry_backoff_seconds

    @classmethod
    def from_config(cls) -> PlanetsNuClient:
        return cls(get_config().planets_api_base_url)

    def _request_with_retry(
        self,
        operation: str,
        request: Callable[[httpx.Client], httpx.Response],
        *,
        timeout_seconds: float | None = None,
    ) -> httpx.Response:
        timeout = self._timeout if timeout_seconds is None else timeout_seconds
        last_exc: httpx.HTTPError | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = request(client)
                    response.raise_for_status()
                    return response
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as exc:
                last_exc = exc
                if not _is_transient_request_error(exc) or attempt >= self._max_attempts:
                    raise
                delay = self._retry_backoff_seconds * attempt
                logger.warning(
                    "Planets.nu %s transient HTTP error (attempt %s/%s): %s; retrying in %.1fs",
                    operation,
                    attempt,
                    self._max_attempts,
                    _safe_httpx_error_summary(exc),
                    delay,
                )
                time.sleep(delay)
        assert last_exc is not None
        raise last_exc

    def _parse_json_from_response(
        self,
        response: httpx.Response,
        *,
        invalid_json_message: str,
    ) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamPlanetsError(invalid_json_message) from exc

    def _json_from_response(
        self,
        response: httpx.Response,
        *,
        invalid_json_message: str,
        unexpected_payload_message: str,
    ) -> dict[str, Any]:
        data = self._parse_json_from_response(
            response,
            invalid_json_message=invalid_json_message,
        )
        if not isinstance(data, dict):
            raise UpstreamPlanetsError(unexpected_payload_message)
        return data

    def login(self, username: str, password: str) -> str:
        url = f"{self._base_url}/login"
        try:
            response = self._request_with_retry(
                "login",
                lambda client: client.get(url, params={"username": username, "password": password}),
            )
            data = self._json_from_response(
                response,
                invalid_json_message="Planets.nu login returned invalid JSON.",
                unexpected_payload_message="Planets.nu login returned an unexpected payload.",
            )
        except httpx.HTTPError as exc:
            logger.warning("Planets.nu login HTTP error: %s", _safe_httpx_error_summary(exc))
            raise UpstreamPlanetsError("Planets.nu login request failed.") from exc

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
            response = self._request_with_retry(
                "loadinfo",
                lambda client: client.get(url, params={"gameid": game_id}),
            )
            return self._json_from_response(
                response,
                invalid_json_message="Planets.nu loadinfo returned invalid JSON.",
                unexpected_payload_message="Planets.nu loadinfo returned an unexpected payload.",
            )
        except httpx.HTTPError as exc:
            logger.warning("Planets.nu loadinfo HTTP error: %s", _safe_httpx_error_summary(exc))
            raise UpstreamPlanetsError("Planets.nu load game info request failed.") from exc

    def load_turn(
        self,
        *,
        game_id: int,
        turn: int | None,
        player_id: int,
        api_key: str | None = None,
    ) -> dict[str, Any]:
        """POST /game/loadturn with form body; returns the full JSON body (success, rst, ...).

        When ``turn`` is ``None``, the turn field is omitted from the form body. Planets.nu
        then returns the latest turn. That path is required for spectator loads (``playerid=0``)
        on the current turn: sending an explicit ``turn`` equal to the live turn errors
        upstream, while omitting ``turn`` succeeds.
        """
        url = f"{self._base_url}/game/loadturn"
        form: dict[str, Any] = {
            "gameid": game_id,
            "playerid": player_id,
        }
        if turn is not None:
            form["turn"] = turn
        if api_key:
            form["apikey"] = api_key
        try:
            response = self._request_with_retry(
                "loadturn",
                lambda client: client.post(url, data=form),
            )
            return self._json_from_response(
                response,
                invalid_json_message="Planets.nu loadturn returned invalid JSON.",
                unexpected_payload_message="Planets.nu loadturn returned an unexpected payload.",
            )
        except httpx.HTTPError as exc:
            logger.warning("Planets.nu loadturn HTTP error: %s", _safe_httpx_error_summary(exc))
            raise UpstreamPlanetsError("Planets.nu load turn request failed.") from exc

    def load_all(self, game_id: int) -> bytes:
        """GET /game/loadall; returns a ZIP of turn files for a finished game."""
        url = f"{self._base_url}/game/loadall"
        loadall_timeout = max(self._timeout, 300.0)
        try:
            response = self._request_with_retry(
                "loadall",
                lambda client: client.get(url, params={"gameid": game_id}),
                timeout_seconds=loadall_timeout,
            )
            body = response.content
        except httpx.HTTPError as exc:
            logger.warning("Planets.nu loadall HTTP error: %s", _safe_httpx_error_summary(exc))
            raise UpstreamPlanetsError("Planets.nu loadall request failed.") from exc

        if not body:
            raise UpstreamPlanetsError("Planets.nu loadall returned an empty response.")

        if body[:1] == b"{":
            try:
                data = json.loads(body)
            except ValueError as exc:
                raise UpstreamPlanetsError("Planets.nu loadall returned invalid JSON.") from exc
            if isinstance(data, dict) and not data.get("success", True):
                detail = data.get("error") or data.get("message") or "Loadall was not successful."
                raise UpstreamPlanetsError(str(detail))

        return body

    def games_list(
        self,
        *,
        status: int | str = 3,
        scope: int | str = 0,
    ) -> list[dict[str, Any]]:
        """GET /games/list; returns finished/public games matching status and scope."""
        url = f"{self._base_url}/games/list"
        params = {"status": status, "scope": scope}
        try:
            response = self._request_with_retry(
                "games list",
                lambda client: client.get(url, params=params),
            )
            data = self._parse_json_from_response(
                response,
                invalid_json_message="Planets.nu games list returned invalid JSON.",
            )
        except httpx.HTTPError as exc:
            logger.warning("Planets.nu games list HTTP error: %s", _safe_httpx_error_summary(exc))
            raise UpstreamPlanetsError("Planets.nu games list request failed.") from exc

        if isinstance(data, list):
            games = data
        elif isinstance(data, dict):
            if not data.get("success", True):
                detail = (
                    data.get("error") or data.get("message") or "Games list was not successful."
                )
                raise UpstreamPlanetsError(str(detail))
            games_raw = data.get("games", data)
            if not isinstance(games_raw, list):
                raise UpstreamPlanetsError("Planets.nu games list returned an unexpected payload.")
            games = games_raw
        else:
            raise UpstreamPlanetsError("Planets.nu games list returned an unexpected payload.")

        parsed: list[dict[str, Any]] = []
        for item in games:
            if not isinstance(item, dict):
                raise UpstreamPlanetsError("Planets.nu games list entry was not an object.")
            parsed.append(item)
        return parsed
