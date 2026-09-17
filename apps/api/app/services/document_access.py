from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.authz.policies import can_read_document
from app.models.document import Document
from app.models.document_access import DocumentAccess
from app.models.user import User
from app.schemas.enums import Role


def readable_document_clause(actor: User):
    if actor.role == Role.ADMIN.value:
        return True
    return or_(
        Document.owner_id == actor.id,
        exists().where(DocumentAccess.document_id == Document.id, DocumentAccess.user_id == actor.id),
    )


def can_view_document(*, db: Session, actor: User, document: Document) -> bool:
    if can_read_document(actor, document):
        return True
    return db.scalar(
        select(DocumentAccess.user_id).where(
            DocumentAccess.document_id == document.id,
            DocumentAccess.user_id == actor.id,
        )
    ) is not None


def can_manage_document(*, actor: User, document: Document) -> bool:
    return actor.role == Role.ADMIN.value or document.owner_id == actor.id
