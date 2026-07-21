from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_admin, require_current_user
from app.models.audit_log import AuditLog
from app.models.provider_key import ProviderKey
from app.models.user import User
from app.schemas.enums import Provider
from app.schemas.provider_settings import (
    ProviderKeyModelSettingsUpdate,
    ProviderKeyRead,
    ProviderKeyTestResponse,
    ProviderKeysListResponse,
    ProviderKeyUpsert,
    ProviderModelOptionsListResponse,
    ProviderModelOptionsRead,
    normalize_available_models,
)
from app.services.provider_keys import (
    ProviderKeyNotConfiguredError,
    delete_provider_key,
    get_provider_key,
    list_shared_provider_keys,
    list_provider_keys,
    test_provider_key_configuration,
    update_provider_key_model_settings,
    upsert_provider_key,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/settings", tags=["provider-settings"])


def _read_provider_key(provider_key: ProviderKey) -> ProviderKeyRead:
    provider = Provider(provider_key.provider)
    return ProviderKeyRead(
        provider=provider,
        base_url=provider_key.base_url,
        default_model=provider_key.default_model,
        available_models=normalize_available_models(provider, provider_key.available_models, provider_key.default_model),
        api_key_fingerprint=provider_key.api_key_fingerprint,
        has_key=True,
    )


@router.get("/provider-keys", response_model=ProviderKeysListResponse)
def get_provider_keys(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ProviderKeysListResponse:
    return ProviderKeysListResponse(
        provider_keys=[_read_provider_key(item) for item in list_provider_keys(db=db, actor=current_user)]
    )


@router.get("/provider-models", response_model=ProviderModelOptionsListResponse)
def get_provider_models(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> ProviderModelOptionsListResponse:
    return ProviderModelOptionsListResponse(
        provider_models=[
            ProviderModelOptionsRead(
                provider=Provider(item.provider),
                default_model=item.default_model,
                available_models=normalize_available_models(Provider(item.provider), item.available_models, item.default_model),
                has_key=True,
            )
            for item in list_shared_provider_keys(db=db)
        ]
    )


@router.put("/provider-keys/{provider}", response_model=ProviderKeyRead)
def put_provider_key(
    provider: Provider,
    payload: ProviderKeyUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ProviderKeyRead:
    existing = get_provider_key(db=db, owner_id=current_user.id, provider=provider)
    provider_key = upsert_provider_key(
        db=db,
        actor=current_user,
        provider=provider,
        api_key=payload.api_key,
        base_url=payload.base_url,
        default_model=payload.default_model,
        available_models=payload.available_models,
    )
    _audit(
        db,
        current_user,
        "provider_key.saved",
        provider_key,
        {"provider": provider.value, "default_model": provider_key.default_model, "base_url": provider_key.base_url},
    )
    db.commit()
    db.refresh(provider_key)
    return _read_provider_key(provider_key)


@router.patch("/provider-keys/{provider}", response_model=ProviderKeyRead)
def patch_provider_key_model_settings(
    provider: Provider,
    payload: ProviderKeyModelSettingsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ProviderKeyRead:
    provider_key = update_provider_key_model_settings(
        db=db,
        actor=current_user,
        provider=provider,
        default_model=payload.default_model,
        available_models=payload.available_models,
    )
    if provider_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider key is not configured")

    _audit(
        db,
        current_user,
        "provider_key.updated",
        provider_key,
        {
            "provider": provider.value,
            "default_model": provider_key.default_model,
            "available_models": provider_key.available_models,
        },
    )
    db.commit()
    db.refresh(provider_key)
    return _read_provider_key(provider_key)


@router.post("/provider-keys/{provider}/test", response_model=ProviderKeyTestResponse)
def test_provider_key(
    provider: Provider,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> ProviderKeyTestResponse:
    try:
        result = test_provider_key_configuration(db=db, actor=current_user, provider=provider)
    except ProviderKeyNotConfiguredError as exc:
        record_audit(
            db=db,
            actor_id=current_user.id,
            action="provider_key.test_failure",
            entity_type="provider_key",
            entity_id=None,
            metadata={"provider": provider.value, "reason": "not_configured"},
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


@router.delete("/provider-keys/{provider}")
def remove_provider_key(
    provider: Provider,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
) -> dict[str, str]:
    provider_key = get_provider_key(db=db, owner_id=current_user.id, provider=provider)
    if provider_key is not None:
        _audit(db, current_user, "provider_key.deleted", provider_key, {"provider": provider.value})
    delete_provider_key(db=db, actor=current_user, provider=provider)
    return {"status": "deleted"}


def _audit(db: Session, actor: User, action: str, provider_key: ProviderKey, metadata: dict | None = None) -> None:
    record_audit(
        db=db,
        actor_id=actor.id,
        action=action,
        entity_type="provider_key",
        entity_id=provider_key.id,
        metadata=metadata or {},
    )
