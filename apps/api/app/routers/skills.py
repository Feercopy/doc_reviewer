from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import require_admin, require_current_user
from app.models.audit_log import AuditLog
from app.models.skill import Skill
from app.models.user import User
from app.schemas.skills import SkillCreate, SkillPatch, SkillRead, SkillsListResponse
from app.services.skills import (
    SkillConflictError,
    SkillNotFoundError,
    SkillSourceValidationError,
    archive_skill_version,
    create_skill_version,
    get_skill,
    list_active_skills,
    patch_skill_version,
    read_skill,
    refresh_skill_source,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/skills", tags=["skills"])
admin_router = APIRouter(prefix="/admin/skills", tags=["admin-skills"])


@router.get("", response_model=SkillsListResponse)
def list_skills(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> SkillsListResponse:
    return SkillsListResponse(skills=[read_skill(skill) for skill in list_active_skills(db=db)])


@router.get("/{skill_id}", response_model=SkillRead)
def get_skill_detail(
    skill_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_current_user),
) -> SkillRead:
    try:
        return read_skill(get_skill(db=db, skill_id=skill_id))
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found") from exc


@admin_router.get("", response_model=SkillsListResponse)
def list_admin_skills(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SkillsListResponse:
    del admin
    return SkillsListResponse(skills=[read_skill(skill) for skill in db.query(Skill).order_by(Skill.created_at.desc()).all()])


@admin_router.post("", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
def create_skill(
    payload: SkillCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SkillRead:
    try:
        skill = create_skill_version(db=db, payload=payload, author_id=admin.id)
    except SkillConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Skill version already exists") from exc
    except SkillSourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _audit(db, admin, "skill.created", skill)
    db.commit()
    db.refresh(skill)
    return read_skill(skill)


@admin_router.patch("/{skill_id}", response_model=SkillRead)
def patch_skill(
    skill_id: UUID,
    payload: SkillPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SkillRead:
    try:
        skill = patch_skill_version(db=db, skill_id=skill_id, payload=payload)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found") from exc
    except SkillSourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _audit(db, admin, "skill.updated", skill)
    db.commit()
    db.refresh(skill)
    return read_skill(skill)


@admin_router.post("/{skill_id}/archive", response_model=SkillRead)
def archive_skill(
    skill_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SkillRead:
    try:
        skill = archive_skill_version(db=db, skill_id=skill_id)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found") from exc

    _audit(db, admin, "skill.archived", skill)
    db.commit()
    db.refresh(skill)
    return read_skill(skill)


@admin_router.post("/{skill_id}/refresh-source", response_model=SkillRead)
def refresh_skill(
    skill_id: UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> SkillRead:
    try:
        skill = refresh_skill_source(db=db, skill_id=skill_id)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found") from exc
    except SkillSourceValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    _audit(db, admin, "skill.source_refreshed", skill)
    db.commit()
    db.refresh(skill)
    return read_skill(skill)


def _audit(db: Session, actor: User, action: str, skill: Skill) -> None:
    record_audit(
        db=db,
        actor_id=actor.id,
        action=action,
        entity_type="skill",
        entity_id=skill.id,
        metadata={
            "name": skill.name,
            "version": skill.version,
            "skill_type": skill.skill_type,
            "source_fingerprint": skill.source_fingerprint,
        },
    )
