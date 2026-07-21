from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.skill import Skill
from app.schemas.enums import EntityStatus
from app.schemas.skills import SkillCreate, SkillPatch, SkillRead, SkillSourceSnapshot
from app.services.skill_sources import (
    SkillSourceValidationError,
    refresh_skill_source_material,
    resolve_skill_source_material,
    validate_result_schema_path,
)


class SkillNotFoundError(ValueError):
    pass


class SkillConflictError(ValueError):
    pass


def list_active_skills(*, db: Session) -> list[Skill]:
    statement = select(Skill).where(Skill.status == EntityStatus.ACTIVE.value).order_by(Skill.name, Skill.version)
    return list(db.execute(statement).scalars().all())


def get_skill(*, db: Session, skill_id) -> Skill:
    skill = db.get(Skill, skill_id)
    if skill is None or skill.status == EntityStatus.DELETED.value:
        raise SkillNotFoundError("Skill not found")
    return skill


def create_skill_version(*, db: Session, payload: SkillCreate, author_id) -> Skill:
    validate_result_schema_path(payload.result_schema_path)
    material = resolve_skill_source_material(
        source_type=payload.source_type,
        source_uri=payload.source_uri,
        source_entrypoint=payload.source_entrypoint,
        prompt_text=payload.prompt_text,
        source_metadata=payload.source_metadata,
    )
    skill = Skill(
        name=payload.name,
        description=payload.description,
        version=payload.version,
        skill_type=payload.skill_type.value,
        supported_document_types=[item.value for item in payload.supported_document_types],
        source_type=payload.source_type.value,
        source_uri=payload.source_uri,
        source_entrypoint=payload.source_entrypoint,
        source_revision=material.source_revision,
        source_fingerprint=material.source_fingerprint,
        source_metadata=material.source_metadata,
        prompt_text=material.prompt_text,
        result_schema_path=payload.result_schema_path,
        status=EntityStatus.ACTIVE.value,
        author_id=author_id,
    )
    db.add(skill)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise SkillConflictError("Skill version already exists") from exc
    return skill


def patch_skill_version(*, db: Session, skill_id, payload: SkillPatch) -> Skill:
    skill = get_skill(db=db, skill_id=skill_id)
    if payload.description is not None:
        skill.description = payload.description
    if payload.supported_document_types is not None:
        skill.supported_document_types = [item.value for item in payload.supported_document_types]
    if payload.source_uri is not None:
        skill.source_uri = payload.source_uri
    if payload.source_entrypoint is not None:
        skill.source_entrypoint = payload.source_entrypoint
    if payload.source_metadata is not None:
        skill.source_metadata = payload.source_metadata
    if payload.prompt_text is not None:
        skill.prompt_text = payload.prompt_text
    if payload.result_schema_path is not None:
        validate_result_schema_path(payload.result_schema_path)
        skill.result_schema_path = payload.result_schema_path

    material = refresh_skill_source_material(skill)
    skill.prompt_text = material.prompt_text
    skill.source_revision = material.source_revision
    skill.source_fingerprint = material.source_fingerprint
    skill.source_metadata = material.source_metadata
    return skill


def archive_skill_version(*, db: Session, skill_id) -> Skill:
    skill = get_skill(db=db, skill_id=skill_id)
    skill.status = EntityStatus.ARCHIVED.value
    return skill


def refresh_skill_source(*, db: Session, skill_id) -> Skill:
    skill = get_skill(db=db, skill_id=skill_id)
    material = refresh_skill_source_material(skill)
    skill.prompt_text = material.prompt_text
    skill.source_revision = material.source_revision
    skill.source_fingerprint = material.source_fingerprint
    skill.source_metadata = material.source_metadata
    return skill


def skill_source_snapshot(skill: Skill) -> dict:
    return {
        "name": skill.name,
        "version": skill.version,
        "skill_type": skill.skill_type,
        "source_type": skill.source_type,
        "source_uri": skill.source_uri,
        "source_entrypoint": skill.source_entrypoint,
        "source_revision": skill.source_revision,
        "source_fingerprint": skill.source_fingerprint,
        "source_metadata": skill.source_metadata,
        "result_schema_path": skill.result_schema_path,
    }


def read_skill(skill: Skill) -> SkillRead:
    return SkillRead(
        id=skill.id,
        name=skill.name,
        description=skill.description,
        version=skill.version,
        skill_type=skill.skill_type,
        supported_document_types=skill.supported_document_types,
        result_schema_path=skill.result_schema_path,
        status=skill.status,
        source_snapshot=SkillSourceSnapshot(
            source_type=skill.source_type,
            source_uri=skill.source_uri,
            source_entrypoint=skill.source_entrypoint,
            source_revision=skill.source_revision,
            source_fingerprint=skill.source_fingerprint,
            source_metadata=skill.source_metadata,
        ),
        created_at=skill.created_at,
        updated_at=skill.updated_at,
    )


__all__ = [
    "SkillConflictError",
    "SkillNotFoundError",
    "SkillSourceValidationError",
    "archive_skill_version",
    "create_skill_version",
    "get_skill",
    "list_active_skills",
    "patch_skill_version",
    "read_skill",
    "refresh_skill_source",
    "skill_source_snapshot",
]
