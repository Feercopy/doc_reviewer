from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, JSON, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.models.base import Base, TimestampMixin


class ProviderKey(TimestampMixin, Base):
    __tablename__ = "provider_keys"
    __table_args__ = (
        UniqueConstraint("owner_id", "provider", name="uq_provider_keys_owner_provider"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String, nullable=True)
    default_model: Mapped[str] = mapped_column(String, nullable=False)
    available_models: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    encrypted_api_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    api_key_fingerprint: Mapped[str] = mapped_column(String, nullable=False)
