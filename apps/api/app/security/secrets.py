from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet

from app.core.config import get_settings


def _fernet(secret_key: str | None = None) -> Fernet:
    material = (secret_key or get_settings().app_secret_key).encode("utf-8")
    return Fernet(urlsafe_b64encode(sha256(material).digest()))


def encrypt_secret(plaintext: str, *, secret_key: str | None = None) -> bytes:
    return _fernet(secret_key).encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes, *, secret_key: str | None = None) -> str:
    return _fernet(secret_key).decrypt(ciphertext).decode("utf-8")
