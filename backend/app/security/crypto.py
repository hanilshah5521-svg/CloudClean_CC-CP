"""At-rest encryption for OAuth tokens (Fernet: AES-128-CBC + HMAC-SHA256).

A refresh token is a long-lived key to the user's whole Drive and Gmail, so
it is never written to the database in plain text. The Fernet key comes from
TOKEN_ENCRYPTION_KEY if set, otherwise it is derived from SECRET_KEY —
rotating either one invalidates stored tokens, and users simply reconnect.
"""
import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

logger = logging.getLogger("cloudclean")


def _fernet() -> Fernet:
    if settings.token_encryption_key:
        return Fernet(settings.token_encryption_key.encode())
    digest = hashlib.sha256(("cloudclean-token-key:" + settings.resolved_secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken:
        # Key rotated, or a plain-text token from before encryption existed.
        # Treat it as missing: the user is asked to reconnect.
        logger.warning("Stored OAuth token could not be decrypted; user must reconnect.")
        return ""


class EncryptedText(TypeDecorator):
    """A Text column that is transparently encrypted on write, decrypted on read."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value or "")

    def process_result_value(self, value, dialect):
        return decrypt(value or "")
