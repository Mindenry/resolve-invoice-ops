"""Symmetric encryption for integration credentials."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config.settings import settings
from app.core.errors import ConfigurationError


def _fernet() -> Fernet:
    return Fernet(settings.fernet_key())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ConfigurationError(
            "Stored integration credential could not be decrypted. The application secret may have changed.",
            code="credential_decryption_failed",
        ) from exc


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:2]}{'•' * 8}{value[-2:]}"
