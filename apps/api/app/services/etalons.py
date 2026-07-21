from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.authz.policies import can_publish_etalon
from app.models.analysis import Analysis
from app.models.document import Document
from app.models.etalon import Etalon
from app.models.user import User
from app.schemas.enums import (
    CheckStatus,
    DocumentParseStatus,
    DocumentType,
    EtalonSource,
    EtalonStatus,
    Role,
    RunStatus,
    Severity,
    Verdict,
)
from app.schemas.etalons import EtalonDraftCreate, EtalonPayload, EtalonUpdate
from app.services.analyses import get_analysis_for_actor
from app.services.audit import record_audit
from app.services.documents import create_document_from_local_file, create_document_from_upload
from app.services.gate2_benchmark_cases import (
    Gate2BenchmarkCase,
    discover_gate2_benchmark_cases,
    gate2_case_source_metadata,
    gate2_case_to_etalon_payload,
    parse_gate2_etalon_csv,
)
from app.storage.local import LocalDocumentStorage


class EtalonNotFoundError(ValueError):
    pass


class EtalonForbiddenError(ValueError):
    pass


class EtalonPreconditionError(ValueError):
    pass


@dataclass
class Gate2BenchmarkImportResult:
    imported_count: int = 0
    skipped_count: int = 0
    updated_count: int = 0
    unmatched_count: int = 0
    parse_document_ids: list[UUID] = field(default_factory=list)
    etalons: list[Etalon] = field(default_factory=list)


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
    record_audit(
        db=db,
        actor_id=actor.id,
        action="etalon.created",
        entity_type="etalon",
        entity_id=etalon.id,
        metadata={"document_id": str(document.id), "source": etalon.source, "status": etalon.status},
    )
    db.commit()
    db.refresh(etalon)
    return etalon


def import_gate2_benchmark_etalons(
    *,
    db: Session,
    actor: User,
    storage: LocalDocumentStorage,
    benchmark_dir: Path,
    activate: bool,
) -> Gate2BenchmarkImportResult:
    if actor.role != Role.ADMIN.value:
        raise EtalonForbiddenError("Only admin can import Gate2 benchmark etalons")

    result = Gate2BenchmarkImportResult()
    cases = discover_gate2_benchmark_cases(benchmark_dir)
    existing_etalons = _existing_gate2_etalons(db)
    for case in cases:
        parsed = parse_gate2_etalon_csv(case.etalon_path)
        metadata = gate2_case_source_metadata(case, parsed)
        existing = _matching_gate2_etalon(existing_etalons, metadata)
        if existing is not None:
            result.skipped_count += 1
            result.etalons.append(existing)
            continue

        document = _find_existing_gate2_document(db=db, metadata=metadata)
        if document is None:
            document = create_document_from_local_file(
                db=db,
                actor=actor,
                storage=storage,
                source_path=case.original_path,
                title=case.name,
                manual_document_type=DocumentType.GATE_2,
            )
            result.parse_document_ids.append(document.id)
        elif document.parse_status != DocumentParseStatus.COMPLETED.value:
            result.parse_document_ids.append(document.id)

        etalon_payload = gate2_case_to_etalon_payload(case)
        etalon = Etalon(
            document_id=document.id,
            author_id=actor.id,
            source=EtalonSource.GATE2_BENCHMARK.value,
            document_type=DocumentType.GATE_2.value,
            real_defense_status=None,
            defense_comments=None,
            expected_verdict=etalon_payload.expected_verdict.value,
            layer_1=[item.model_dump(mode="json") for item in etalon_payload.layer_1],
            layer_2=[item.model_dump(mode="json") for item in etalon_payload.layer_2],
            key_findings=etalon_payload.key_findings,
            forbidden_false_findings=etalon_payload.forbidden_false_findings,
            source_metadata=metadata,
            status=EtalonStatus.ACTIVE.value if activate else EtalonStatus.DRAFT.value,
            version=1,
            raw_file_visible_to_all=False,
        )
        db.add(etalon)
        result.imported_count += 1
        result.etalons.append(etalon)
        existing_etalons.append(etalon)
        record_audit(
            db=db,
            actor_id=actor.id,
            action="etalon.created",
            entity_type="etalon",
            entity_id=etalon.id,
            metadata={"document_id": str(document.id), "source": etalon.source, "status": etalon.status},
        )

    db.commit()
    for etalon in result.etalons:
        db.refresh(etalon)
    return result


def create_past_defense_etalon(
    *,
    db: Session,
    actor: User,
    storage: LocalDocumentStorage,
    upload: UploadFile,
    title: str | None,
    document_type: DocumentType,
    expected_verdict: Verdict,
    real_defense_status: str,
    defense_comments: str,
    defense_date: str | None,
    notes: str | None,
    raw_file_visible_to_all: bool,
) -> tuple[Document, Etalon]:
    document = create_document_from_upload(
        db=db,
        actor=actor,
        storage=storage,
        upload=upload,
        title=title,
        manual_document_type=document_type,
    )
    etalon = Etalon(
        document_id=document.id,
        author_id=actor.id,
        source=EtalonSource.IMPORTED_DEFENSE.value,
        document_type=document_type.value,
        real_defense_status=real_defense_status.strip(),
        defense_comments=_format_defense_comments(
            defense_comments=defense_comments,
            defense_date=defense_date,
            notes=notes,
        ),
        expected_verdict=expected_verdict.value,
        layer_1=[],
        layer_2=[],
        key_findings=[],
        forbidden_false_findings=[],
        status=EtalonStatus.DRAFT.value,
        version=1,
        raw_file_visible_to_all=raw_file_visible_to_all,
    )
    db.add(etalon)
    record_audit(
        db=db,
        actor_id=actor.id,
        action="etalon.created",
        entity_type="etalon",
        entity_id=etalon.id,
        metadata={"document_id": str(document.id), "source": etalon.source, "status": etalon.status},
    )
    db.commit()
    db.refresh(document)
    db.refresh(etalon)
    return document, etalon


def list_etalons_for_actor(*, db: Session, actor: User) -> list[Etalon]:
    statement = select(Etalon)
    if _can_review_etalon(actor):
        statement = statement.where(~Etalon.status.in_([EtalonStatus.ARCHIVED.value, EtalonStatus.DELETED.value]))
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
    record_audit(
        db=db,
        actor_id=actor.id,
        action="etalon.updated",
        entity_type="etalon",
        entity_id=etalon.id,
        metadata={"version": etalon.version, "status": etalon.status},
    )
    db.commit()
    db.refresh(etalon)
    return etalon


def publish_etalon(*, db: Session, actor: User, etalon_id: UUID) -> Etalon:
    etalon = _get_existing_etalon(db=db, etalon_id=etalon_id)
    if not can_publish_etalon(actor):
        raise EtalonForbiddenError("Only admin or annotator can publish etalons")
    if etalon.status == EtalonStatus.DELETED.value:
        raise EtalonNotFoundError("Etalon not found")
    if etalon.status == EtalonStatus.ARCHIVED.value:
        raise EtalonPreconditionError("Archived etalon cannot be published")
    etalon.status = EtalonStatus.ACTIVE.value
    etalon.version += 1
    record_audit(
        db=db,
        actor_id=actor.id,
        action="etalon.published",
        entity_type="etalon",
        entity_id=etalon.id,
        metadata={"version": etalon.version},
    )
    db.commit()
    db.refresh(etalon)
    return etalon


def archive_etalon(*, db: Session, actor: User, etalon_id: UUID) -> Etalon:
    etalon = _get_existing_etalon(db=db, etalon_id=etalon_id)
    if etalon.status == EtalonStatus.DELETED.value:
        raise EtalonNotFoundError("Etalon not found")
    if not _can_review_etalon(actor):
        raise EtalonForbiddenError("Only admin or annotator can archive etalons")
    etalon.status = EtalonStatus.ARCHIVED.value
    etalon.version += 1
    record_audit(
        db=db,
        actor_id=actor.id,
        action="etalon.archived",
        entity_type="etalon",
        entity_id=etalon.id,
        metadata={"version": etalon.version},
    )
    db.commit()
    db.refresh(etalon)
    return etalon


def delete_etalon(*, db: Session, actor: User, etalon_id: UUID) -> None:
    if actor.role != Role.ADMIN.value:
        raise EtalonForbiddenError("Only admin can delete etalons")
    etalon = _get_existing_etalon(db=db, etalon_id=etalon_id)
    if etalon.status == EtalonStatus.DELETED.value:
        raise EtalonNotFoundError("Etalon not found")
    previous_status = etalon.status
    etalon.status = EtalonStatus.DELETED.value
    etalon.version += 1
    record_audit(
        db=db,
        actor_id=actor.id,
        action="etalon.deleted",
        entity_type="etalon",
        entity_id=etalon.id,
        metadata={"version": etalon.version, "status": {"from": previous_status, "to": etalon.status}},
    )
    db.commit()


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

    layer_1 = _normalize_layer_1(structured.get("layer_1"))
    if not layer_1:
        layer_1 = _findings_to_layer_1(structured.get("findings"))

    layer_2 = _normalize_layer_2(structured.get("layer_2"), layer_1)
    if not layer_2:
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


def _normalize_layer_1(items: object) -> list[dict]:
    if not isinstance(items, list):
        return []
    layer_1 = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        item_id = _normalized_item_id(item.get("id"), prefix="L1", index=index)
        evidence = _evidence_items(
            item.get("evidence"),
            fallback=item.get("summary") or item.get("issue") or item.get("impact") or item.get("title"),
        )
        summary = _first_text(
            item.get("summary"),
            item.get("issue"),
            item.get("impact"),
            _first_evidence_quote(evidence),
            item.get("title"),
            "No summary supplied",
        )
        layer_1.append(
            {
                "id": item_id,
                "dimension": _first_text(item.get("dimension"), item.get("check"), "Analysis finding"),
                "status": _status_value(item.get("status"), item.get("severity")),
                "severity": _severity_value(item.get("severity")),
                "title": _first_text(item.get("title"), item.get("issue"), item_id),
                "summary": summary,
                "evidence": evidence,
                "recommendation": _first_text(item.get("recommendation"), item.get("expected_fix"), ""),
                "confidence": _confidence_value(item.get("confidence")),
            }
        )
    return layer_1


def _normalize_layer_2(items: object, layer_1: list[dict]) -> list[dict]:
    if not isinstance(items, list):
        return []
    parent_ids = {str(item["id"]) for item in layer_1 if isinstance(item, dict) and item.get("id")}
    default_parent_id = next(iter(parent_ids), None)
    layer_2 = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        parent_id = str(item.get("parent_layer_1_id") or default_parent_id or "")
        if not parent_id:
            continue
        evidence = _evidence_items(
            item.get("evidence"),
            fallback=(
                item.get("finding")
                or item.get("issue")
                or item.get("atomic_issue")
                or item.get("risk")
                or item.get("title")
                or item.get("question")
            ),
        )
        layer_2.append(
            {
                "id": _normalized_item_id(item.get("id"), prefix="L2", index=index),
                "parent_layer_1_id": parent_id,
                "check": _first_text(
                    item.get("check"),
                    item.get("question"),
                    item.get("title"),
                    item.get("atomic_issue"),
                    f"Check {index}",
                ),
                "status": _status_value(item.get("status"), item.get("severity")),
                "severity": _severity_value(item.get("severity")),
                "finding": _first_text(
                    item.get("finding"),
                    item.get("issue"),
                    item.get("atomic_issue"),
                    item.get("risk"),
                    item.get("title"),
                    _first_evidence_quote(evidence),
                    "No finding supplied",
                ),
                "evidence": evidence,
                "expected_fix": _first_text(item.get("expected_fix"), item.get("recommendation"), ""),
                "confidence": _confidence_value(item.get("confidence")),
            }
        )
    return layer_2


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


def _normalized_item_id(value: object, *, prefix: str, index: int) -> str:
    candidate = _first_text(value, f"{prefix}-{index:03d}")
    return candidate if candidate.startswith(f"{prefix}-") else f"{prefix}-{candidate}"


def _severity_value(value: object) -> str:
    candidate = str(value) if value is not None else ""
    return candidate if candidate in {item.value for item in Severity} else Severity.MEDIUM.value


def _status_value(value: object, severity: object) -> str:
    candidate = str(value) if value is not None else ""
    if candidate in {item.value for item in CheckStatus}:
        return candidate
    severity_value = _severity_value(severity)
    if severity_value in {Severity.CRITICAL.value, Severity.HIGH.value}:
        return CheckStatus.FAIL.value
    return CheckStatus.PARTIAL.value


def _evidence_items(value: object, *, fallback: object) -> list[dict]:
    if isinstance(value, list):
        evidence = []
        for item in value:
            if isinstance(item, dict):
                quote = _first_text(item.get("quote"), item.get("text"), item.get("evidence"), "")
                location = _first_text(item.get("location"), "analysis output")
                if quote:
                    evidence.append({"quote": quote, "location": location})
            else:
                quote = _first_text(item, "")
                if quote:
                    evidence.append({"quote": quote, "location": "analysis output"})
        if evidence:
            return evidence

    quote = _first_text(value, fallback, "No evidence supplied")
    return [{"quote": quote, "location": "analysis output"}]


def _first_evidence_quote(evidence: list[dict]) -> str:
    if not evidence:
        return ""
    return str(evidence[0].get("quote") or "")


def _confidence_value(value: object) -> float | None:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _first_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, str):
            text = str(value).strip()
            if text:
                return text
    return ""


def _effective_document_type(document: Document) -> str:
    return document.manual_document_type or document.detected_document_type or DocumentType.UNKNOWN.value


def _format_defense_comments(*, defense_comments: str, defense_date: str | None, notes: str | None) -> str:
    parts = []
    if defense_date and defense_date.strip():
        parts.append(f"Defense date: {defense_date.strip()}")
    if defense_comments.strip():
        parts.append(defense_comments.strip())
    if notes and notes.strip():
        parts.append(f"Notes: {notes.strip()}")
    return "\n\n".join(parts)


def _get_existing_etalon(*, db: Session, etalon_id: UUID) -> Etalon:
    etalon = db.get(Etalon, etalon_id)
    if etalon is None:
        raise EtalonNotFoundError("Etalon not found")
    return etalon


def _existing_gate2_etalons(db: Session) -> list[Etalon]:
    statement = select(Etalon).where(Etalon.source == EtalonSource.GATE2_BENCHMARK.value)
    return list(db.execute(statement).scalars().all())


def _matching_gate2_etalon(etalons: list[Etalon], metadata: dict) -> Etalon | None:
    for etalon in etalons:
        existing_metadata = etalon.source_metadata or {}
        if (
            existing_metadata.get("case_name") == metadata.get("case_name")
            and existing_metadata.get("original_sha256") == metadata.get("original_sha256")
            and existing_metadata.get("etalon_csv_sha256") == metadata.get("etalon_csv_sha256")
        ):
            return etalon
    return None


def _find_existing_gate2_document(*, db: Session, metadata: dict) -> Document | None:
    statement = select(Document).where(Document.file_hash_sha256 == metadata.get("original_sha256"))
    for document in db.execute(statement).scalars().all():
        if document.original_filename == Path(str(metadata.get("original_path", ""))).name:
            return document
    return None


def _can_read_etalon(actor: User, etalon: Etalon) -> bool:
    if etalon.status == EtalonStatus.DELETED.value:
        return False
    if _can_review_etalon(actor):
        return True
    if etalon.status == EtalonStatus.ACTIVE.value:
        return True
    return etalon.status == EtalonStatus.DRAFT.value and etalon.author_id == actor.id


def _can_edit_etalon(actor: User, etalon: Etalon) -> bool:
    if etalon.status == EtalonStatus.DELETED.value:
        return False
    if _can_review_etalon(actor):
        return etalon.status != EtalonStatus.ARCHIVED.value
    return etalon.status == EtalonStatus.DRAFT.value and etalon.author_id == actor.id


def _can_review_etalon(actor: User) -> bool:
    return actor.role in {Role.ADMIN.value, Role.ANNOTATOR.value}
