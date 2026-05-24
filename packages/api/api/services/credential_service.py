"""Planets.nu account API key storage at ``credentials/accounts/*``."""

import re

from api.errors import NotFoundError, ValidationError
from api.storage.base import StorageBackend

_USERNAME_SAFE = re.compile(r"^[a-zA-Z0-9_.-]+$")


class CredentialService:
    """Read and write stored planets.nu API keys per account name."""

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

    def _api_key_path(self, username: str) -> str:
        if not username or not _USERNAME_SAFE.fullmatch(username):
            raise ValidationError(
                "username must be non-empty and contain only letters, digits, "
                "underscores, dots, and hyphens"
            )
        return f"credentials/accounts/{username}/api_key"

    def get_stored_api_key(self, username: str) -> str | None:
        path = self._api_key_path(username)
        try:
            raw = self._storage.get(path)
        except NotFoundError:
            return None
        if isinstance(raw, str) and raw.strip():
            return raw
        return None

    def store_api_key(self, username: str, api_key: str) -> None:
        self._storage.put(self._api_key_path(username), api_key)
