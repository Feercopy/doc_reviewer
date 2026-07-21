from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_admin
from app.models.document import Document
from app.models.etalon import Etalon
from app.models.user import User
from app.schemas.admin import AdminEtalonRead, AdminEtalonsListResponse
from app.schemas.enums import DocumentType, EtalonStatus
from app.services.etalons import EtalonForbiddenError, EtalonNotFoundError, delete_etalon

router = APIRouter(prefix="/admin/etalons", tags=["admin-etalons"])


@router.get("", response_model=AdminEtalonsListResponse)
def list_admin_etalons(
    status: EtalonStatus | None = None,
    author_id: UUID | None = None,
    document_type: DocumentType | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminEtalonsListResponse:
    statement = (
        select(Etalon, Document, User)
        .join(Document, Document.id == Etalon.document_id)
        .join(User, User.id == Etalon.author_id)
    )
    if status is not None:
        statement = statement.where(Etalon.status == status.value)
    if author_id is not None:
        statement = statement.where(Etalon.author_id == author_id)
    if document_type is not None:
        statement = statement.where(Etalon.document_type == document_type.value)
    if status is None:
        statement = statement.where(Etalon.status != EtalonStatus.DELETED.value)
    statement = statement.order_by(Etalon.updated_at.desc())
    return AdminEtalonsListResponse(
        etalons=[_read_etalon(etalon, document, author) for etalon, document, author in db.execute(statement).all()]
    )


@router.delete("/{etalon_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_admin_etalon(
    etalon_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    try:
        delete_etalon(db=db, actor=admin, etalon_id=etalon_id)
    except EtalonNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Etalon not found") from exc
    except EtalonForbiddenError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _read_etalon(etalon: Etalon, document: Document, author: User) -> AdminEtalonRead:
    return AdminEtalonRead(
        id=etalon.id,
        document_id=etalon.document_id,
        document_title=document.title,
        author_id=etalon.author_id,
        author_login=author.login,
        source=etalon.source,
        document_type=etalon.document_type,
        expected_verdict=etalon.expected_verdict,
        layer_1_count=len(etalon.layer_1),
        layer_2_count=len(etalon.layer_2),
        status=etalon.status,
        version=etalon.version,
        raw_file_visible_to_all=etalon.raw_file_visible_to_all,
        created_at=etalon.created_at,
        updated_at=etalon.updated_at,
    )
