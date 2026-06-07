import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from uuid import UUID

from app.core.config import get_settings


SESSION_COOKIE_NAME = "gate_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 7


@dataclass(frozen=True)
class SessionPayload:
    user_id: UUID
    issued_at: int


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload: str) -> str:
    secret = get_settings().app_secret_key.encode("utf-8")
    return hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()


def create_session_cookie_value(user_id: UUID) -> str:
    payload = {
        "user_id": str(user_id),
        "iat": int(time.time()),
    }
    encoded_payload = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign(encoded_payload)
    return f"{encoded_payload}.{signature}"


def parse_session_cookie_value(cookie_value: str) -> SessionPayload | None:
    try:
        encoded_payload, signature = cookie_value.split(".", 1)
    except ValueError:
        return None

    expected_signature = _sign(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        payload = json.loads(_b64_decode(encoded_payload))
        issued_at = int(payload["iat"])
        if int(time.time()) - issued_at > SESSION_MAX_AGE_SECONDS:
            return None
        return SessionPayload(user_id=UUID(payload["user_id"]), issued_at=issued_at)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
