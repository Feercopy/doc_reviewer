from typing import Any

from app.schemas.enums import Role


def _role(actor: Any) -> str:
    return str(getattr(actor, "role"))


def _id(value: Any) -> str:
    return str(value)


def _is_admin(actor: Any) -> bool:
    return _role(actor) == Role.ADMIN.value


def _is_annotator(actor: Any) -> bool:
    return _role(actor) == Role.ANNOTATOR.value


def can_read_document(actor: Any, document: Any) -> bool:
    return _is_admin(actor) or _id(getattr(actor, "id")) == _id(getattr(document, "owner_id"))


def can_read_document_raw(actor: Any, document: Any, etalon: Any | None = None) -> bool:
    if can_read_document(actor, document):
        return True
    return bool(etalon and getattr(etalon, "raw_file_visible_to_all", False))


def can_read_analysis(actor: Any, analysis: Any, document: Any) -> bool:
    del analysis
    return can_read_document(actor, document)


def can_delete_analysis(actor: Any, analysis: Any) -> bool:
    return _is_admin(actor) or _id(getattr(actor, "id")) == _id(getattr(analysis, "user_id"))


def can_read_raw_output(actor: Any, analysis: Any) -> bool:
    return _is_admin(actor)


def can_publish_etalon(actor: Any) -> bool:
    return _is_admin(actor) or _is_annotator(actor)


def can_manage_users(actor: Any) -> bool:
    return _is_admin(actor)


def can_manage_skills(actor: Any) -> bool:
    return _is_admin(actor)


def can_manage_benchmarks(actor: Any) -> bool:
    return _is_admin(actor)
