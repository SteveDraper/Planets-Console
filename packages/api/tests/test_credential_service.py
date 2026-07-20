"""Unit tests for account API key obfuscation and CredentialService."""

from __future__ import annotations

import pytest
from api.credentials.machine_id import MachineIdError
from api.credentials.obfuscation import (
    decrypt_account_api_key,
    encrypt_account_api_key,
    is_obfuscated_envelope,
)
from api.errors import LoginCredentialsRequiredError, ValidationError
from api.services.credential_service import (
    CredentialService,
    looks_like_account_api_key_auth_failure,
)
from api.storage.memory_asset import MemoryAssetBackend


class FakePlanets:
    def __init__(self, api_key: str = "new-key") -> None:
        self.api_key = api_key
        self.login_calls: list[tuple[str, str]] = []

    def login(self, username: str, password: str) -> str:
        self.login_calls.append((username, password))
        return self.api_key


def _svc(
    storage: MemoryAssetBackend | None = None,
    *,
    machine_id: str = "test-machine-id",
    secret: str | None = None,
) -> tuple[CredentialService, MemoryAssetBackend]:
    backend = storage or MemoryAssetBackend(initial={})
    service = CredentialService(
        backend,
        machine_id_reader=lambda: machine_id,
        obfuscation_secret=secret,
    )
    return service, backend


def test_encrypt_decrypt_round_trip():
    envelope = encrypt_account_api_key(
        "secret-key",
        machine_id="machine-a",
        secret=None,
    )
    assert is_obfuscated_envelope(envelope)
    assert decrypt_account_api_key(envelope, machine_id="machine-a", secret=None) == "secret-key"


def test_decrypt_fails_with_wrong_machine_id():
    envelope = encrypt_account_api_key("secret-key", machine_id="machine-a", secret=None)
    with pytest.raises(ValueError):
        decrypt_account_api_key(envelope, machine_id="machine-b", secret=None)


def test_decrypt_fails_with_wrong_secret():
    envelope = encrypt_account_api_key("secret-key", machine_id="m", secret="s1")
    with pytest.raises(ValueError):
        decrypt_account_api_key(envelope, machine_id="m", secret="s2")


def test_store_and_get_obfuscated():
    svc, backend = _svc()
    svc.store_api_key("alice", "plain-key")
    raw = backend.get("credentials/accounts/alice/api_key")
    assert is_obfuscated_envelope(raw)
    assert raw != "plain-key"
    assert svc.get_stored_api_key("alice") == "plain-key"


def test_lazy_migrate_plaintext():
    svc, backend = _svc()
    backend.put("credentials/accounts/bob/api_key", "legacy-plain")
    assert svc.get_stored_api_key("bob") == "legacy-plain"
    raw = backend.get("credentials/accounts/bob/api_key")
    assert is_obfuscated_envelope(raw)
    assert svc.get_stored_api_key("bob") == "legacy-plain"


def test_probe_true_false_and_undecryptable():
    svc, _ = _svc()
    assert svc.probe("nobody") is False
    svc.store_api_key("alice", "k")
    assert svc.probe("alice") is True

    svc2, backend2 = _svc(machine_id="machine-a")
    svc2.store_api_key("carol", "k")
    envelope = backend2.get("credentials/accounts/carol/api_key")
    backend3 = MemoryAssetBackend(initial={})
    backend3.put("credentials/accounts/carol/api_key", envelope)
    wrong = CredentialService(
        backend3,
        machine_id_reader=lambda: "machine-b",
        obfuscation_secret=None,
    )
    assert wrong.probe("carol") is False


def test_exchange_always_calls_login_and_replaces():
    svc, _ = _svc()
    planets = FakePlanets("key-1")
    svc.exchange("alice", "pw", planets)  # type: ignore[arg-type]
    assert planets.login_calls == [("alice", "pw")]
    assert svc.get_stored_api_key("alice") == "key-1"

    planets.api_key = "key-2"
    svc.exchange("alice", "pw2", planets)  # type: ignore[arg-type]
    assert planets.login_calls == [("alice", "pw"), ("alice", "pw2")]
    assert svc.get_stored_api_key("alice") == "key-2"


def test_ensure_with_password_always_exchanges():
    svc, _ = _svc()
    planets = FakePlanets("first")
    svc.store_api_key("alice", "old")
    planets.api_key = "replaced"
    assert svc.ensure_api_key_for_user("alice", "secret", planets) == "replaced"  # type: ignore[arg-type]
    assert planets.login_calls == [("alice", "secret")]
    assert svc.get_stored_api_key("alice") == "replaced"


def test_ensure_without_password_uses_stored():
    svc, _ = _svc()
    planets = FakePlanets()
    svc.store_api_key("alice", "cached")
    assert svc.ensure_api_key_for_user("alice", None, planets) == "cached"  # type: ignore[arg-type]
    assert planets.login_calls == []


def test_ensure_without_password_raises_when_missing():
    svc, _ = _svc()
    with pytest.raises(LoginCredentialsRequiredError):
        svc.ensure_api_key_for_user("alice", None, FakePlanets())  # type: ignore[arg-type]


def test_drop_and_invalidate():
    svc, _ = _svc()
    svc.store_api_key("alice", "k")
    svc.drop("alice")
    assert svc.probe("alice") is False
    svc.store_api_key("alice", "k2")
    svc.invalidate("alice")
    assert svc.probe("alice") is False
    svc.drop("missing")  # no-op


def test_invalidate_if_auth_failure():
    svc, _ = _svc()
    svc.store_api_key("alice", "k")
    assert svc.invalidate_if_auth_failure("alice", "Invalid apikey") is True
    assert svc.probe("alice") is False
    svc.store_api_key("alice", "k")
    assert svc.invalidate_if_auth_failure("alice", "turn not found") is False
    assert svc.probe("alice") is True


@pytest.mark.parametrize(
    "detail,expected",
    [
        ("Invalid apikey", True),
        ("Not logged in", True),
        ("turn missing", False),
    ],
)
def test_looks_like_auth_failure(detail: str, expected: bool):
    assert looks_like_account_api_key_auth_failure(detail) is expected


def test_exchange_requires_password():
    svc, _ = _svc()
    with pytest.raises(ValidationError):
        svc.exchange("alice", "", FakePlanets())  # type: ignore[arg-type]


def test_machine_id_reader_failure_on_store():
    backend = MemoryAssetBackend(initial={})

    def boom() -> str:
        raise MachineIdError("no id")

    svc = CredentialService(backend, machine_id_reader=boom, obfuscation_secret=None)
    with pytest.raises(Exception, match="machine id"):
        svc.store_api_key("alice", "k")
