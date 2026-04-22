import base64
import hashlib
import hmac
import os
from functools import lru_cache
from typing import Final

from cryptography.fernet import Fernet, InvalidToken
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
_ENCODING: Final[str] = "utf-8"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _derive_key() -> bytes:
    """Legacy key (kept for backward-compat decrypt only)."""
    return hashlib.sha256(settings.master_key.encode(_ENCODING)).digest()


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Build a Fernet instance from settings.master_key.

    Accepts either a urlsafe base64-encoded 32-byte Fernet key directly,
    or any passphrase which is hashed (SHA-256) then base64-encoded.
    """
    raw = settings.master_key.encode(_ENCODING)
    try:
        # If master_key is already a valid Fernet key, use it as-is.
        return Fernet(raw)
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
        return Fernet(derived)


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    token = _fernet().encrypt(value.encode(_ENCODING))
    return token.decode(_ENCODING)


def _legacy_decrypt(value: str) -> str:
    raw = base64.urlsafe_b64decode(value.encode(_ENCODING))
    digest, cipher = raw[:32], raw[32:]
    key = _derive_key()
    expected = hmac.new(key, cipher, hashlib.sha256).digest()
    if not hmac.compare_digest(digest, expected):
        raise ValueError("Invalid encrypted payload")
    data = bytes(b ^ key[index % len(key)] for index, b in enumerate(cipher))
    return data.decode(_ENCODING)


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode(_ENCODING)).decode(_ENCODING)
    except InvalidToken:
        # Backward compatibility: data encrypted with the previous XOR+HMAC scheme.
        return _legacy_decrypt(value)


def create_session_token() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode(_ENCODING)
