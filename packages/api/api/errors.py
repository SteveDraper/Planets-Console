"""FastAPI HTTP exception handling for the Core API."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Type

from fastapi import Request
from fastapi.responses import JSONResponse

from api.exceptions import (
    ConflictError,
    CoreAPIError,
    FleetMaterializationTimeoutError,
    LoginCredentialsRequiredError,
    NotFoundError,
    PlanetsConsoleError,
    UpstreamPlanetsError,
    ValidationError,
)

__all__ = [
    "ConflictError",
    "CoreAPIError",
    "FleetMaterializationTimeoutError",
    "LoginCredentialsRequiredError",
    "NotFoundError",
    "PlanetsConsoleError",
    "UpstreamPlanetsError",
    "ValidationError",
    "make_http_exception_handler",
]

logger = logging.getLogger(__name__)


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
