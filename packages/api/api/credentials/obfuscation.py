"""HKDF + AES-GCM wrapping for account API keys (machine-bound obfuscation).

HKDF IKM is the OS machine id bytes, optionally concatenated with a configured
secret (NUL-separated). Changing either input invalidates prior ciphertext.
Salt and info are fixed app strings for envelope version 1.
"""

from __future__ import annotations

import base64
import os
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ACCOUNT_API_KEY_ENVELOPE_VERSION = 1
_HKDF_SALT = b"planets-console-account-api-key-salt-v1"
_HKDF_INFO = b"planets-console-account-api-key-v1"
_NONCE_SIZE = 12


def is_obfuscated_envelope(value: object) -> bool:
    """True when ``value`` looks like a versioned AES-GCM account API key envelope."""
    if not isinstance(value, dict):
        return False
    if value.get("v") != ACCOUNT_API_KEY_ENVELOPE_VERSION:
        return False
    return isinstance(value.get("nonce"), str) and isinstance(value.get("ciphertext"), str)


def derive_wrapping_key(*, machine_id: str, secret: str | None) -> bytes:
    """Derive a 256-bit AES key from machine id and optional config secret."""
    ikm = machine_id.encode("utf-8")
    if secret:
        # Secret is mixed into IKM so rotating it or the machine id both break decrypt.
        ikm = ikm + b"\0" + secret.encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=_HKDF_INFO,
    ).derive(ikm)


def encrypt_account_api_key(
    plaintext: str,
    *,
    machine_id: str,
    secret: str | None,
) -> dict[str, Any]:
    """Return a JSON-serializable AES-GCM envelope for ``plaintext``."""
    key = derive_wrapping_key(machine_id=machine_id, secret=secret)
    nonce = os.urandom(_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return {
        "v": ACCOUNT_API_KEY_ENVELOPE_VERSION,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def decrypt_account_api_key(
    envelope: dict[str, Any],
    *,
    machine_id: str,
    secret: str | None,
) -> str:
    """Decrypt a versioned envelope; raises ``ValueError`` on any decrypt failure."""
    if not is_obfuscated_envelope(envelope):
        raise ValueError("Account API key envelope is malformed.")
    try:
        nonce = base64.b64decode(envelope["nonce"], validate=True)
        ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("Account API key envelope encoding is invalid.") from exc
    if len(nonce) != _NONCE_SIZE:
        raise ValueError("Account API key envelope nonce has unexpected length.")
    key = derive_wrapping_key(machine_id=machine_id, secret=secret)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except Exception as exc:
        raise ValueError("Account API key decrypt failed.") from exc
    return plaintext.decode("utf-8")
