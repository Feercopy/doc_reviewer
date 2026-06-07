from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.provider_key import ProviderKey
from app.models.user import User
from app.schemas.enums import Provider
from app.security.secrets import decrypt_secret, encrypt_secret


class ProviderKeyNotConfiguredError(ValueError):
    pass


class ProviderKeyTestResult:
    def __init__(
        self,
        *,
        provider: Provider,
        status: str,
        message: str,
        default_model: str | None,
        base_url: str | None,
    ) -> None:
        self.provider = provider
        self.status = status
        self.message = message
        self.default_model = default_model
        self.base_url = base_url


def upsert_provider_key(
    *,
    db: Session,
    actor: User,
    provider: Provider,
    api_key: str,
    base_url: str | None,
    default_model: str,
) -> ProviderKey:
    provider_key = get_provider_key(db=db, owner_id=actor.id, provider=provider)
    if provider_key is None:
        provider_key = ProviderKey(owner_id=actor.id, provider=provider.value)
        db.add(provider_key)

    provider_key.base_url = base_url
    provider_key.default_model = default_model
    provider_key.encrypted_api_key = encrypt_secret(api_key)
    provider_key.api_key_fingerprint = _fingerprint(provider, api_key)
    db.commit()
    db.refresh(provider_key)
    return provider_key


def list_provider_keys(*, db: Session, actor: User) -> list[ProviderKey]:
    statement = select(ProviderKey).where(ProviderKey.owner_id == actor.id).order_by(ProviderKey.provider)
    return list(db.execute(statement).scalars().all())


def get_provider_key(*, db: Session, owner_id, provider: Provider) -> ProviderKey | None:
    statement = select(ProviderKey).where(
        ProviderKey.owner_id == owner_id,
        ProviderKey.provider == provider.value,
    )
    return db.execute(statement).scalar_one_or_none()


def delete_provider_key(*, db: Session, actor: User, provider: Provider) -> bool:
    provider_key = get_provider_key(db=db, owner_id=actor.id, provider=provider)
    if provider_key is None:
        return False
    db.delete(provider_key)
    db.commit()
    return True


def decrypt_provider_key(provider_key: ProviderKey) -> str:
    return decrypt_secret(provider_key.encrypted_api_key)


def test_provider_key_configuration(*, db: Session, actor: User, provider: Provider) -> ProviderKeyTestResult:
    provider_key = get_provider_key(db=db, owner_id=actor.id, provider=provider)
    if provider_key is None:
        if provider == Provider.HERMES and get_settings().hermes_enabled:
            return ProviderKeyTestResult(
                provider=provider,
                status="ok",
                message="Hermes provider is enabled.",
                default_model=None,
                base_url=get_settings().hermes_http_url,
            )
        raise ProviderKeyNotConfiguredError("Provider key is not configured")

    decrypt_provider_key(provider_key)
    return ProviderKeyTestResult(
        provider=provider,
        status="ok",
        message="Provider key is configured and decryptable.",
        default_model=provider_key.default_model,
        base_url=provider_key.base_url,
    )


def _fingerprint(provider: Provider, api_key: str) -> str:
    suffix = api_key[-4:] if len(api_key) >= 4 else api_key
    return f"{provider.value}:...{suffix}"
