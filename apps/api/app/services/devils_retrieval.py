import hashlib
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.analysis import Analysis, PredictedCommentRun
from app.models.document import Document
from app.models.skill_source import RetrievalSnapshot, SkillSourceSnapshot
from app.storage.local import LocalDocumentStorage


RETRIEVAL_VERSION = "deterministic-lexical-v1"
TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def build_devils_retrieval_dossier(
    *,
    source_snapshot_artifact_path: Path | str,
    document: Any,
    analysis: Any,
    top_k: int = 3,
) -> dict[str, Any]:
    files_root = _files_root(source_snapshot_artifact_path)
    candidates = _collect_candidates(files_root)
    query_text = _build_query_text(document=document, analysis=analysis)
    query_tokens = _tokenize(query_text)
    corpus_fingerprint = _fingerprint_files(candidates)
    query_fingerprint = hashlib.sha256(query_text.encode("utf-8")).hexdigest()

    selected_items = {
        "top_cases": _score_group(candidates.get("top_cases", []), query_tokens, top_k=top_k),
        "top_patterns": _score_group(candidates.get("top_patterns", []), query_tokens, top_k=top_k),
        "top_heuristics": _score_group(candidates.get("top_heuristics", []), query_tokens, top_k=top_k),
        "top_persona_question_examples": _score_group(
            candidates.get("top_persona_question_examples", []),
            query_tokens,
            top_k=top_k,
        ),
    }
    selected_paths = [
        item["path"]
        for group in selected_items.values()
        for item in group
    ]

    return {
        "retrieval_mode": "deterministic_topk",
        "retrieval_version": RETRIEVAL_VERSION,
        "corpus_fingerprint": corpus_fingerprint,
        "query_fingerprint": query_fingerprint,
        "selected_items": selected_items,
        "selected_paths": selected_paths,
        "retrieval_rationale": {
            "scoring": "lexical token overlap; ties sorted by relative source path",
            "top_k": top_k,
        },
    }


def create_devils_retrieval_snapshot(
    *,
    db: Session,
    storage: LocalDocumentStorage,
    source_snapshot: SkillSourceSnapshot,
    predicted_run: PredictedCommentRun,
    document: Document,
    analysis: Analysis,
    top_k: int = 3,
) -> RetrievalSnapshot:
    dossier = build_devils_retrieval_dossier(
        source_snapshot_artifact_path=source_snapshot.artifact_path,
        document=document,
        analysis=analysis,
        top_k=top_k,
    )
    snapshot_id = uuid4()
    artifact_path = storage.save_retrieval_snapshot(
        snapshot_id=snapshot_id,
        dossier=dossier,
        source_snapshot_artifact_path=source_snapshot.artifact_path,
    )
    snapshot = RetrievalSnapshot(
        id=snapshot_id,
        predicted_comment_run_id=predicted_run.id,
        retrieval_mode=dossier["retrieval_mode"],
        retrieval_version=dossier["retrieval_version"],
        corpus_fingerprint=dossier["corpus_fingerprint"],
        query_fingerprint=dossier["query_fingerprint"],
        selected_items=dossier["selected_items"],
        artifact_path=str(artifact_path),
    )
    db.add(snapshot)
    db.flush()
    return snapshot


def _files_root(source_snapshot_artifact_path: Path | str) -> Path:
    root = Path(source_snapshot_artifact_path).expanduser().resolve() / "files"
    if not root.is_dir():
        raise RuntimeError("source_snapshot_unavailable")
    return root


def _collect_candidates(files_root: Path) -> dict[str, list[Path]]:
    return {
        "top_cases": _paths_under(files_root, "wiki-ic/cases"),
        "top_patterns": _paths_under(files_root, "wiki-ic/patterns"),
        "top_heuristics": [
            *_paths_under(files_root, "wiki-ic/heuristics"),
            *_paths_under(files_root, "wiki-ic/domains"),
        ],
        "top_persona_question_examples": [
            *_paths_under(files_root, "wiki-ic/personas"),
            *_paths_under(files_root, "wiki-ic/eval"),
        ],
    }


def _paths_under(files_root: Path, relative_dir: str) -> list[Path]:
    directory = files_root / relative_dir
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.rglob("*.md") if path.is_file())


def _score_group(paths: list[Path], query_tokens: set[str], *, top_k: int) -> list[dict[str, Any]]:
    scored = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        tokens = _tokenize(text)
        score = sum(1 for token in query_tokens if token in tokens)
        relative_path = _relative_source_path(path)
        scored.append(
            {
                "path": relative_path,
                "score": score,
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "excerpt": _excerpt(text),
            }
        )
    return sorted(scored, key=lambda item: (-item["score"], item["path"]))[:top_k]


def _build_query_text(*, document: Any, analysis: Any) -> str:
    structured_output = getattr(analysis, "structured_output", None) or {}
    return "\n".join(
        [
            getattr(document, "title", "") or "",
            getattr(document, "detected_document_type", "") or "",
            getattr(document, "manual_document_type", "") or "",
            getattr(document, "parsed_text", "") or "",
            getattr(analysis, "summary", "") or "",
            json.dumps(structured_output, ensure_ascii=False, sort_keys=True),
        ]
    )


def _fingerprint_files(candidates: dict[str, list[Path]]) -> str:
    digest = hashlib.sha256()
    paths = sorted(path for group in candidates.values() for path in group)
    for path in paths:
        digest.update(_relative_source_path(path).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _relative_source_path(path: Path) -> str:
    parts = path.parts
    if "files" in parts:
        index = parts.index("files")
        return Path(*parts[index + 1 :]).as_posix()
    return path.name


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text) if len(token) > 2}


def _excerpt(text: str, *, limit: int = 500) -> str:
    normalized = " ".join(text.split())
    return normalized[:limit]
