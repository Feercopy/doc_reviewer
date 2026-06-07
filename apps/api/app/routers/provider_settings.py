from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_current_user
from app.models.audit_log import AuditLog
from app.models.provider_key import ProviderKey
from app.models.user import User
from app.schemas.enums import Provider
from app.schemas.provider_settings import (
    ProviderKeyRead,
    ProviderKeyTestResponse,
    ProviderKeysListResponse,
    ProviderKeyUpsert,
)
from app.services.provider_keys import (
    ProviderKeyNotConfiguredError,
    delete_provider_key,
    get_provider_key,
    list_provider_keys,
    test_provider_key_configuration,
    upsert_provider_key,
)

router = APIRouter(prefix="/settings/provider-keys", tags=["provider-settings"])


def _read_provider_key(provider_key: ProviderKey) -> ProviderKeyRead:
    return ProviderKeyRead(
        provider=Provider(provider_key.provider),
        base_url=provider_key.base_url,
        default_model=provider_key.default_model,
        api_key_fingerprint=provider_key.api_key_fingerprint,
        has_key=True,
    )


@router.get("", response_model=ProviderKeysListResponse)
def get_provider_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> ProviderKeysListResponse:
    return ProviderKeysListResponse(
        provider_keys=[_read_provider_key(item) for item in list_provider_keys(db=db, actor=current_user)]
    )


@router.put("/{provider}", response_model=ProviderKeyRead)
def put_provider_key(
    provider: Provider,
    payload: ProviderKeyUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> ProviderKeyRead:
    existing = get_provider_key(db=db, owner_id=current_user.id, provider=provider)
    provider_key = upsert_provider_key(
        db=db,
        actor=current_user,
        provider=provider,
        api_key=payload.api_key,
        base_url=payload.base_url,
        default_model=payload.default_model,
    )
    _audit(
        db,
        current_user,
        "provider_key.replace" if existing else "provider_key.create",
        provider_key,
        {"provider": provider.value, "default_model": provider_key.default_model, "base_url": provider_key.base_url},
    )
    db.commit()
    db.refresh(provider_key)
    return _read_provider_key(provider_key)


@router.post("/{provider}/test", response_model=ProviderKeyTestResponse)
def test_provider_key(
    provider: Provider,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> ProviderKeyTestResponse:
    try:
        result = test_provider_key_configuration(db=db, actor=current_user, provider=provider)
    except ProviderKeyNotConfiguredError as exc:
        db.add(
            AuditLog(
                actor_id=current_user.id,
                action="provider_key.test_failure",
                entity_type="provider_key",
                entity_id=None,
                metadata_={"provider": provider.value, "reason": "not_configured"},
            )
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    provider_key = get_provider_key(db=db, owner_id=current_user.id, provider=provider)
    if provider_key is not None:
        _audit(db, current_user, "provider_key.test", provider_key, {"provider": provider.value})
        db.commit()
    return ProviderKeyTestResponse(
        provider=result.provider,
        status=result.status,
        message=result.message,
        default_model=result.default_model,
        base_url=result.base_url,
    )


@router.delete("/{provider}")
def remove_provider_key(
    provider: Provider,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> dict[str, str]:
    provider_key = get_provider_key(db=db, owner_id=current_user.id, provider=provider)
    if provider_key is not None:
        _audit(db, current_user, "provider_key.delete", provider_key, {"provider": provider.value})
    delete_provider_key(db=db, actor=current_user, provider=provider)
    return {"status": "deleted"}


def _audit(db: Session, actor: User, action: str, provider_key: ProviderKey, metadata: dict | None = None) -> None:
    db.add(
        AuditLog(
            actor_id=actor.id,
            action=action,
            entity_type="provider_key",
            entity_id=provider_key.id,
            metadata_=metadata or {},
        )
    )
