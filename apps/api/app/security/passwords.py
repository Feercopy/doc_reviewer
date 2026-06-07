import base64
import hashlib
import hmac
import os


try:
    from passlib.context import CryptContext
except ModuleNotFoundError:
    CryptContext = None


password_context = CryptContext(schemes=["argon2"], deprecated="auto") if CryptContext else None
PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 390_000


def _hash_password_pbkdf2(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return ".".join(
        [
            PBKDF2_PREFIX,
            str(PBKDF2_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def _verify_password_pbkdf2(password: str, password_hash: str) -> bool:
    try:
        prefix, iterations_raw, salt_raw, digest_raw = password_hash.split(".", 3)
        if prefix != PBKDF2_PREFIX:
            return False
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected_digest = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations_raw),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual_digest, expected_digest)


def hash_password(password: str) -> str:
    if password_context is not None:
        return password_context.hash(password)
    return _hash_password_pbkdf2(password)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith(f"{PBKDF2_PREFIX}."):
        return _verify_password_pbkdf2(password, password_hash)
    if password_context is None:
        return False
    return password_context.verify(password, password_hash)
