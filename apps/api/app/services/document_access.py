from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.authz.policies import can_read_document
from app.models.document import Document
from app.models.document_access import DocumentAccess
from app.models.superuser_owner_access import SuperuserOwnerAccess
from app.models.user import User
from app.schemas.enums import Role


def readable_document_clause(actor: User):
    if actor.role == Role.ADMIN.value:
        return True
    clauses = [
        Document.owner_id == actor.id,
        exists().where(DocumentAccess.document_id == Document.id, DocumentAccess.user_id == actor.id),
    ]
    if actor.role == Role.SUPERUSER.value:
        clauses.append(
            exists().where(
                SuperuserOwnerAccess.superuser_id == actor.id,
                SuperuserOwnerAccess.owner_id == Document.owner_id,
            )
        )
    return or_(*clauses)


def can_view_document(*, db: Session, actor: User, document: Document) -> bool:
    if can_read_document(actor, document):
        return True
    if actor.role == Role.SUPERUSER.value and has_superuser_owner_access(db=db, actor=actor, owner_id=document.owner_id):
        return True
    return db.scalar(
        select(DocumentAccess.user_id).where(
            DocumentAccess.document_id == document.id,
            DocumentAccess.user_id == actor.id,
        )
    ) is not None


def has_superuser_owner_access(*, db: Session, actor: User, owner_id: UUID) -> bool:
    if actor.role != Role.SUPERUSER.value:
        return False
    return db.scalar(
        select(SuperuserOwnerAccess.owner_id).where(
            SuperuserOwnerAccess.superuser_id == actor.id,
            SuperuserOwnerAccess.owner_id == owner_id,
        )
    ) is not None


def can_launch_document_analysis(*, db: Session, actor: User, document: Document) -> bool:
    return can_manage_document(actor=actor, document=document) or (
        actor.role == Role.SUPERUSER.value and can_view_document(db=db, actor=actor, document=document)
    )


def can_manage_document(*, actor: User, document: Document) -> bool:
    return actor.role == Role.ADMIN.value or document.owner_id == actor.id
