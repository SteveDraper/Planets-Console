"""Planets.nu account API key storage at ``credentials/accounts/*``.

Keys are stored with machine-bound obfuscation (AES-GCM). Legacy plaintext
strings are accepted on read and rewritten obfuscated (lazy credential migrate).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from api.config import get_config
from api.credentials.machine_id import MachineIdError, read_os_machine_id
from api.credentials.obfuscation import (
    decrypt_account_api_key,
    encrypt_account_api_key,
    is_obfuscated_envelope,
)
from api.errors import (
    CoreAPIError,
    LoginCredentialsRequiredError,
    NotFoundError,
    ValidationError,
)
from api.planets_nu import PlanetsNuClient
from api.storage.base import StorageBackend

logger = logging.getLogger(__name__)

_USERNAME_SAFE = re.compile(r"^[a-zA-Z0-9_.-]+$")

# Precise Planets.nu rejection phrases (case-insensitive substring).
# Keep this list narrow: bare tokens like "apikey" / "authentication" false-positive
# and wipe a still-valid stored key.
_AUTH_FAILURE_PHRASES = (
    "invalid apikey",
    "invalid api key",
    "invalid api-key",
    "not logged in",
    "not logged-in",
    "login required",
)


def looks_like_account_api_key_auth_failure(detail: str) -> bool:
    """True when an upstream error message matches a known key/session rejection phrase."""
    lowered = detail.lower()
    return any(phrase in lowered for phrase in _AUTH_FAILURE_PHRASES)


class CredentialService:
    """Read and write stored planets.nu API keys per account name."""

    def __init__(
        self,
        storage: StorageBackend,
        *,
        machine_id_reader: Callable[[], str] | None = None,
        obfuscation_secret: str | None | object = ...,
    ) -> None:
        self._storage = storage
        self._machine_id_reader = machine_id_reader or read_os_machine_id
        # Ellipsis means "read from ApiConfig at use time" so tests can set_config later.
        self._obfuscation_secret_override = obfuscation_secret

    def _api_key_path(self, username: str) -> str:
        if not username or not _USERNAME_SAFE.fullmatch(username):
            raise ValidationError(
                "username must be non-empty and contain only letters, digits, "
                "underscores, dots, and hyphens"
            )
        return f"credentials/accounts/{username}/api_key"

    def _resolved_secret(self) -> str | None:
        if self._obfuscation_secret_override is not ...:
            secret = self._obfuscation_secret_override
            if secret is None:
                return None
            if not isinstance(secret, str):
                raise TypeError("obfuscation_secret must be str | None")
            return secret
        return get_config().credentials_obfuscation_secret

    def _machine_id(self) -> str:
        try:
            value = self._machine_id_reader()
        except MachineIdError:
            raise
        except Exception as exc:
            raise MachineIdError("Failed to read OS machine id.") from exc
        if not isinstance(value, str) or not value.strip():
            raise MachineIdError("OS machine id was empty.")
        return value.strip()

    def _wrap(self, plaintext: str) -> dict[str, Any]:
        return encrypt_account_api_key(
            plaintext,
            machine_id=self._machine_id(),
            secret=self._resolved_secret(),
        )

    def _unwrap(self, envelope: dict[str, Any]) -> str:
        return decrypt_account_api_key(
            envelope,
            machine_id=self._machine_id(),
            secret=self._resolved_secret(),
        )

    def get_stored_api_key(self, username: str) -> str | None:
        """Return the plaintext account API key, or None if missing / undecryptable.

        Legacy plaintext values are migrated to an obfuscated envelope on read.
        """
        path = self._api_key_path(username)
        try:
            raw = self._storage.get(path)
        except NotFoundError:
            return None

        if isinstance(raw, str):
            plaintext = raw.strip()
            if not plaintext:
                return None
            try:
                self._storage.put(path, self._wrap(plaintext))
            except MachineIdError:
                logger.warning(
                    "Lazy credential migrate skipped for %s: machine id unavailable",
                    username,
                )
            return plaintext

        if is_obfuscated_envelope(raw):
            try:
                plaintext = self._unwrap(raw)  # type: ignore[arg-type]
            except (MachineIdError, ValueError):
                return None
            return plaintext.strip() or None

        return None

    def store_api_key(self, username: str, api_key: str) -> None:
        """Persist ``api_key`` with machine-bound obfuscation."""
        plaintext = api_key.strip()
        if not plaintext:
            raise ValidationError("api_key must be a non-empty string")
        try:
            envelope = self._wrap(plaintext)
        except MachineIdError as exc:
            raise CoreAPIError(
                "Cannot store account API key: OS machine id is unavailable.",
                http_error=500,
            ) from exc
        self._storage.put(self._api_key_path(username), envelope)

    def probe(self, username: str) -> bool:
        """True iff a decryptable account API key exists for ``username`` (no Planets.nu call)."""
        return self.get_stored_api_key(username) is not None

    def exchange(self, username: str, password: str, planets: PlanetsNuClient) -> None:
        """Always login to Planets.nu and replace the stored obfuscated account API key."""
        if not password:
            raise ValidationError("password is required for login exchange")
        api_key = planets.login(username, password)
        self.store_api_key(username, api_key)

    def drop(self, username: str) -> None:
        """Delete stored account API key material for ``username`` (no-op if missing)."""
        path = self._api_key_path(username)
        try:
            self._storage.delete(path)
        except NotFoundError:
            return

    def invalidate(self, username: str) -> None:
        """Account API key invalidation: same durable outcome as drop for the key field."""
        self.drop(username)

    def invalidate_if_auth_failure(self, username: str, detail: str) -> bool:
        """If ``detail`` looks like key rejection, drop the key and return True."""
        if not looks_like_account_api_key_auth_failure(detail):
            return False
        self.invalidate(username)
        return True

    def ensure_api_key_for_user(
        self, username: str, password: str | None, planets: PlanetsNuClient
    ) -> str:
        """Return a usable account API key.

        When ``password`` is provided, always performs login exchange (replace key).
        Otherwise decrypts the stored key or raises ``LoginCredentialsRequiredError``.
        """
        if password is not None and password != "":
            self.exchange(username, password, planets)
            api_key = self.get_stored_api_key(username)
            if not api_key:
                raise LoginCredentialsRequiredError("Login credentials are required.")
            return api_key

        api_key = self.get_stored_api_key(username)
        if not api_key:
            raise LoginCredentialsRequiredError("Login credentials are required.")
        return api_key
