from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.authz.policies import can_publish_etalon
from app.models.analysis import Analysis
from app.models.document import Document
from app.models.etalon import Etalon
from app.models.user import User
from app.schemas.enums import CheckStatus, DocumentType, EtalonSource, EtalonStatus, Role, RunStatus, Severity
from app.schemas.etalons import EtalonDraftCreate, EtalonPayload, EtalonUpdate
from app.services.analyses import get_analysis_for_actor


class EtalonNotFoundError(ValueError):
    pass


class EtalonForbiddenError(ValueError):
    pass


class EtalonPreconditionError(ValueError):
    pass


def create_etalon_draft_from_analysis(
    *,
    db: Session,
    actor: User,
    analysis_id: UUID,
    payload: EtalonDraftCreate,
) -> Etalon:
    analysis = get_analysis_for_actor(db=db, actor=actor, analysis_id=analysis_id)
    if analysis.status != RunStatus.COMPLETED.value:
        raise EtalonPreconditionError("Analysis is not completed")
    if payload.status == EtalonStatus.ARCHIVED:
        raise EtalonPreconditionError("Etalon draft cannot be created as archived")
    if payload.status == EtalonStatus.ACTIVE and not can_publish_etalon(actor):
        raise EtalonForbiddenError("Only admin or annotator can publish active etalons")

    document = db.get(Document, analysis.document_id)
    if document is None:
        raise EtalonPreconditionError("Analysis document is missing")

    etalon_payload = _payload_from_analysis(analysis)
    etalon = Etalon(
        document_id=document.id,
        author_id=actor.id,
        source=EtalonSource.AI_POST_ANNOTATION.value,
        document_type=_effective_document_type(document),
        real_defense_status=None,
        defense_comments=None,
        expected_verdict=etalon_payload.expected_verdict.value,
        layer_1=[item.model_dump(mode="json") for item in etalon_payload.layer_1],
        layer_2=[item.model_dump(mode="json") for item in etalon_payload.layer_2],
        key_findings=etalon_payload.key_findings,
        forbidden_false_findings=etalon_payload.forbidden_false_findings,
        status=payload.status.value,
        version=1,
        raw_file_visible_to_all=False,
    )
    db.add(etalon)
    db.commit()
    db.refresh(etalon)
    return etalon


def list_etalons_for_actor(*, db: Session, actor: User) -> list[Etalon]:
    statement = select(Etalon)
    if _can_review_etalon(actor):
        statement = statement.where(Etalon.status != EtalonStatus.ARCHIVED.value)
    else:
        statement = statement.where(
            or_(
                Etalon.status == EtalonStatus.ACTIVE.value,
                (Etalon.status == EtalonStatus.DRAFT.value) & (Etalon.author_id == actor.id),
            )
        )
    statement = statement.order_by(Etalon.created_at.desc())
    return list(db.execute(statement).scalars().all())


def get_etalon_for_actor(*, db: Session, actor: User, etalon_id: UUID) -> Etalon:
    etalon = db.get(Etalon, etalon_id)
    if etalon is None or not _can_read_etalon(actor, etalon):
        raise EtalonNotFoundError("Etalon not found")
    return etalon


def update_etalon(*, db: Session, actor: User, etalon_id: UUID, payload: EtalonUpdate) -> Etalon:
    etalon = get_etalon_for_actor(db=db, actor=actor, etalon_id=etalon_id)
    if not _can_edit_etalon(actor, etalon):
        raise EtalonForbiddenError("Etalon cannot be edited by current user")

    try:
        merged_payload = EtalonPayload.model_validate(
            {
                "expected_verdict": payload.expected_verdict or etalon.expected_verdict,
                "layer_1": payload.layer_1 if payload.layer_1 is not None else etalon.layer_1,
                "layer_2": payload.layer_2 if payload.layer_2 is not None else etalon.layer_2,
                "key_findings": payload.key_findings if payload.key_findings is not None else etalon.key_findings,
                "forbidden_false_findings": (
                    payload.forbidden_false_findings
                    if payload.forbidden_false_findings is not None
                    else etalon.forbidden_false_findings
                ),
            }
        )
    except ValueError as exc:
        raise EtalonPreconditionError(str(exc)) from exc

    etalon.expected_verdict = merged_payload.expected_verdict.value
    etalon.layer_1 = [item.model_dump(mode="json") for item in merged_payload.layer_1]
    etalon.layer_2 = [item.model_dump(mode="json") for item in merged_payload.layer_2]
    etalon.key_findings = merged_payload.key_findings
    etalon.forbidden_false_findings = merged_payload.forbidden_false_findings
    if "real_defense_status" in payload.model_fields_set:
        etalon.real_defense_status = payload.real_defense_status
    if "defense_comments" in payload.model_fields_set:
        etalon.defense_comments = payload.defense_comments
    if "raw_file_visible_to_all" in payload.model_fields_set:
        etalon.raw_file_visible_to_all = bool(payload.raw_file_visible_to_all)
    etalon.version += 1
    db.commit()
    db.refresh(etalon)
    return etalon


def publish_etalon(*, db: Session, actor: User, etalon_id: UUID) -> Etalon:
    etalon = _get_existing_etalon(db=db, etalon_id=etalon_id)
    if not can_publish_etalon(actor):
        raise EtalonForbiddenError("Only admin or annotator can publish etalons")
    if etalon.status == EtalonStatus.ARCHIVED.value:
        raise EtalonPreconditionError("Archived etalon cannot be published")
    etalon.status = EtalonStatus.ACTIVE.value
    etalon.version += 1
    db.commit()
    db.refresh(etalon)
    return etalon


def archive_etalon(*, db: Session, actor: User, etalon_id: UUID) -> Etalon:
    etalon = _get_existing_etalon(db=db, etalon_id=etalon_id)
    if not _can_review_etalon(actor):
        raise EtalonForbiddenError("Only admin or annotator can archive etalons")
    etalon.status = EtalonStatus.ARCHIVED.value
    etalon.version += 1
    db.commit()
    db.refresh(etalon)
    return etalon


def list_annotation_queue(*, db: Session, actor: User) -> list[Etalon]:
    if not _can_review_etalon(actor):
        raise EtalonForbiddenError("Only admin or annotator can read annotation queue")
    statement = select(Etalon).where(Etalon.status == EtalonStatus.DRAFT.value).order_by(Etalon.created_at.desc())
    return list(db.execute(statement).scalars().all())


def _payload_from_analysis(analysis: Analysis) -> EtalonPayload:
    structured = analysis.structured_output or {}
    verdict = structured.get("verdict") or analysis.verdict
    if not verdict:
        raise EtalonPreconditionError("Analysis has no verdict")

    layer_1 = structured.get("layer_1")
    if not isinstance(layer_1, list):
        layer_1 = _findings_to_layer_1(structured.get("findings"))

    layer_2 = structured.get("layer_2")
    if not isinstance(layer_2, list):
        layer_2 = _checks_to_layer_2(structured.get("checks"), layer_1)

    key_findings = structured.get("key_findings")
    if not isinstance(key_findings, list):
        key_findings = _key_findings_from_layer_1(layer_1)

    forbidden_false_findings = structured.get("forbidden_false_findings")
    if not isinstance(forbidden_false_findings, list):
        forbidden_false_findings = []

    try:
        return EtalonPayload.model_validate(
            {
                "expected_verdict": verdict,
                "layer_1": layer_1,
                "layer_2": layer_2,
                "key_findings": key_findings,
                "forbidden_false_findings": forbidden_false_findings,
            }
        )
    except ValueError as exc:
        raise EtalonPreconditionError(str(exc)) from exc


def _findings_to_layer_1(findings: object) -> list[dict]:
    if not isinstance(findings, list):
        return []
    layer_1 = []
    for index, finding in enumerate(findings, start=1):
        if not isinstance(finding, dict):
            continue
        finding_id = str(finding.get("id") or f"L1-{index:03d}")
        evidence_text = str(finding.get("evidence") or finding.get("summary") or finding.get("title") or "No evidence supplied")
        layer_1.append(
            {
                "id": finding_id if finding_id.startswith("L1-") else f"L1-{finding_id}",
                "dimension": str(finding.get("dimension") or "Analysis finding"),
                "status": CheckStatus.FAIL.value,
                "severity": str(finding.get("severity") or Severity.MEDIUM.value),
                "title": str(finding.get("title") or finding_id),
                "summary": str(finding.get("summary") or evidence_text),
                "evidence": [{"quote": evidence_text, "location": "analysis output"}],
                "recommendation": str(finding.get("recommendation") or ""),
                "confidence": finding.get("confidence"),
            }
        )
    return layer_1


def _checks_to_layer_2(checks: object, layer_1: list[dict]) -> list[dict]:
    if not isinstance(checks, list):
        return []
    parent_id = str(layer_1[0]["id"]) if layer_1 else None
    if parent_id is None:
        return []
    layer_2 = []
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            continue
        status = str(check.get("status") or CheckStatus.PARTIAL.value)
        explanation = str(check.get("explanation") or check.get("name") or "No explanation supplied")
        layer_2.append(
            {
                "id": str(check.get("id") or f"L2-{index:03d}"),
                "parent_layer_1_id": str(check.get("parent_layer_1_id") or parent_id),
                "check": str(check.get("check") or check.get("name") or f"Check {index}"),
                "status": status,
                "severity": str(check.get("severity") or Severity.MEDIUM.value),
                "finding": str(check.get("finding") or explanation),
                "evidence": [{"quote": explanation, "location": "analysis output"}],
                "expected_fix": str(check.get("expected_fix") or ""),
                "confidence": check.get("confidence"),
            }
        )
    return layer_2


def _key_findings_from_layer_1(layer_1: list[dict]) -> list[str]:
    return [str(item["title"]) for item in layer_1 if isinstance(item, dict) and item.get("title")]


def _effective_document_type(document: Document) -> str:
    return document.manual_document_type or document.detected_document_type or DocumentType.UNKNOWN.value


def _get_existing_etalon(*, db: Session, etalon_id: UUID) -> Etalon:
    etalon = db.get(Etalon, etalon_id)
    if etalon is None:
        raise EtalonNotFoundError("Etalon not found")
    return etalon


def _can_read_etalon(actor: User, etalon: Etalon) -> bool:
    if _can_review_etalon(actor):
        return True
    if etalon.status == EtalonStatus.ACTIVE.value:
        return True
    return etalon.status == EtalonStatus.DRAFT.value and etalon.author_id == actor.id


def _can_edit_etalon(actor: User, etalon: Etalon) -> bool:
    if _can_review_etalon(actor):
        return etalon.status != EtalonStatus.ARCHIVED.value
    return etalon.status == EtalonStatus.DRAFT.value and etalon.author_id == actor.id


def _can_review_etalon(actor: User) -> bool:
    return actor.role in {Role.ADMIN.value, Role.ANNOTATOR.value}
