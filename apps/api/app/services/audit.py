from collections.abc import Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

SECRET_KEY_PARTS = ("api_key", "apikey", "password", "secret", "token", "credential")
REDACTED = "[redacted]"


def record_audit(
    *,
    db: Session,
    actor_id: UUID | None,
    action: str,
    entity_type: str,
    entity_id: UUID | None,
    metadata: dict | None = None,
) -> AuditLog:
    audit = AuditLog(
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata_=sanitize_audit_metadata(metadata or {}),
    )
    db.add(audit)
    return audit


def sanitize_audit_metadata(value):
    if isinstance(value, Mapping):
        sanitized = {}
        for key, nested_value in value.items():
            key_text = str(key).lower()
            if any(part in key_text for part in SECRET_KEY_PARTS):
                sanitized[key] = REDACTED
            else:
                sanitized[key] = sanitize_audit_metadata(nested_value)
        return sanitized
    if isinstance(value, list):
        return [sanitize_audit_metadata(item) for item in value]
    return value
