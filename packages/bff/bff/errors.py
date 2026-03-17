"""Exception hierarchy for the BFF package.

All package-raised exceptions should inherit from BFFError (or a descendant).
Each exception class may override `http_error` (default 500) to control the
HTTP status returned to the client.

Uses PlanetsConsoleError from the Core API and the shared exception handler
factory so that BFF and API share the same handling behaviour.
"""

from api.errors import PlanetsConsoleError, make_http_exception_handler

__all__ = [
    "BFFError",
    "make_http_exception_handler",
    "PlanetsConsoleError",
]


class BFFError(PlanetsConsoleError):
    """Root exception for the BFF package.

    All exceptions raised by the BFF should inherit from this (or a
    descendant). Override the class attribute `http_error` for a fixed status
    per exception type.
    """

    http_error: int = 500
