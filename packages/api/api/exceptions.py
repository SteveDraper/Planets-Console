"""Exception hierarchy for the Core API (transport-free).

All package-raised exceptions should inherit from CoreAPIError (or a descendant).
Each exception class may override `http_error` (default 500) to control the
HTTP status returned to the client when handled by the FastAPI layer.
"""

from __future__ import annotations

from api.compute.persistence import PersistDeferredError, PersistDependencyRecovery


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


class FleetMaterializationTimeoutError(CoreAPIError):
    """Coordinated fleet gap-fill did not complete within the waiter timeout."""

    http_error: int = 504


class FleetGapFillEpochInvalidated(CoreAPIError):
    """Fleet gap-fill aborted because invalidation generation bumped mid-chain.

    Callers should treat this as retryable: exit the current leg and re-queue
    (orchestrator epoch discard, stream reschedule, or a later ensure) rather
    than spinning synchronous rematerializations on the same worker.
    """

    http_error: int = 409


class FleetScoresEvidenceOpenError(PersistDeferredError, CoreAPIError):
    """Fleet host-turn persist refused because same-turn scores evidence is open.

    Completing the fleet node would unlock dependents and leave a non-final ledger
    with no automatic rematerialization. Carries a :class:`PersistDependencyRecovery`
    that force_freshes same-turn scores; the orchestrator handles the base
    :class:`PersistDeferredError` generically (demote to ``waiting_deps`` + dep submit).
    """

    http_error: int = 409

    def __init__(self, message: str = "", *, recovery: PersistDependencyRecovery) -> None:
        PersistDeferredError.__init__(self, message, recovery=recovery)
