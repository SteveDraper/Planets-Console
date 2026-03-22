"""Exception hierarchy and HTTP exception handling for the Core API.

All package-raised exceptions should inherit from CoreAPIError (or a descendant).
Each exception class may override `http_error` (default 500) to control the
HTTP status returned to the client.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Type

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class PlanetsConsoleError(Exception):
    """Base for all server-side exceptions that map to an HTTP status.

    Subclass this in each package (CoreAPIError, BFFError) so that handlers
    can return the exception's http_error as the response status.
    """

    http_error: int = 500

    def __init__(self, message: str = "", *, http_error: int | None = None) -> None:
        super().__init__(message)
        if http_error is not None:
            self.http_error = http_error


class CoreAPIError(PlanetsConsoleError):
    """Root exception for the Core REST API package.

    All exceptions raised by the Core API should inherit from this (or a
    descendant). Override the class attribute `http_error` for a fixed status
    per exception type, or pass `http_error=` to the constructor for one-off
    overrides.
    """

    http_error: int = 500


# --- Store / storage layer exceptions (design §6) ---


class NotFoundError(CoreAPIError):
    """Path does not exist (read/update/delete)."""

    http_error: int = 404


class ConflictError(CoreAPIError):
    """Create on existing path, or update would change node type."""

    http_error: int = 409


class ValidationError(CoreAPIError):
    """Invalid payload/path (e.g. reserved @ key, malformed path segment)."""

    http_error: int = 422


class LoginCredentialsRequiredError(CoreAPIError):
    """Stored API key is missing and no password was supplied for refresh."""

    http_error: int = 401


class UpstreamPlanetsError(CoreAPIError):
    """Planets.nu HTTP or transport failure, or an unusable response body."""

    http_error: int = 502


def make_http_exception_handler(
    root_exception_cls: Type[PlanetsConsoleError],
) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    """Return a FastAPI/Starlette exception handler for the given root exception class.

    Use with app.add_exception_handler(Exception, make_http_exception_handler(YourRootError)).

    - Exceptions that are instances of root_exception_cls (or subclasses) are
      returned with status_code = exc.http_error and body {"detail": str(exc)}.
    - All other exceptions are logged at ERROR with stack trace and request
      details, and a 500 response is returned.
    """

    async def handler(request: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, root_exception_cls):
            status = getattr(exc, "http_error", 500)
            return JSONResponse(
                status_code=status,
                content={"detail": str(exc) or "Internal server error"},
            )
        logger.error(
            "Unexpected exception: %s",
            exc,
            exc_info=True,
            extra={
                "url": str(request.url),
                "method": request.method,
                "path": request.url.path,
                "query": str(request.query_params),
            },
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return handler
