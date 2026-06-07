from enum import StrEnum


class Role(StrEnum):
    USER = "user"
    ANNOTATOR = "annotator"
    ADMIN = "admin"


class UserStatus(StrEnum):
    ACTIVE = "active"
    BLOCKED = "blocked"


class DocumentType(StrEnum):
    GATE_1 = "gate_1"
    GATE_2 = "gate_2"
    GATE_3 = "gate_3"
    PROGRESS_REVIEW = "progress_review"
    STREAM_REVIEW = "stream_review"
    STRATEGY_REVIEW = "strategy_review"
    UNKNOWN = "unknown"


class DocumentParseStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EntityStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class SkillType(StrEnum):
    MAIN_ANALYSIS = "main_analysis"
    PREDICTED_COMMENTS = "predicted_comments"
    BENCHMARK_JUDGE = "benchmark_judge"
    PARSER_HELPER = "parser_helper"
    DOCUMENT_CLASSIFIER = "document_classifier"


class SkillSourceType(StrEnum):
    INLINE_PROMPT = "inline_prompt"
    LOCAL_SKILL_REPO = "local_skill_repo"
    LOCAL_KNOWLEDGE_BASE = "local_knowledge_base"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Provider(StrEnum):
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC_COMPATIBLE = "anthropic_compatible"
    HERMES = "hermes"


class Verdict(StrEnum):
    APPROVE = "approve"
    APPROVE_WITH_CONDITIONS = "approve_with_conditions"
    NEED_EVIDENCE = "need_evidence"
    REJECT = "reject"
    UNKNOWN = "unknown"


class CheckStatus(StrEnum):
    PASS = "pass"
    PARTIAL = "partial"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EtalonSource(StrEnum):
    MANUAL = "manual"
    AI_POST_ANNOTATION = "ai_post_annotation"
    IMPORTED_DEFENSE = "imported_defense"


class EtalonStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class FeedbackUsefulness(StrEnum):
    USEFUL = "useful"
    PARTIALLY_USEFUL = "partially_useful"
    USELESS = "useless"
