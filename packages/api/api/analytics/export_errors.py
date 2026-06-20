"""Cycle detection for analytic export resolution."""

from api.errors import CoreAPIError


class ExportCycleDetectedError(CoreAPIError):
    """Same export resolution key was re-entered during one query."""

    http_error = 422
