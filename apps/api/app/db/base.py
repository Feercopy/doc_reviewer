from app.models.base import Base

# Import models so Alembic and metadata.create_all see the full schema.
from app.models.analysis import Analysis, AnalysisCheckRun, AnalysisCheckStep, AnalysisDetailRun, PredictedCommentRun  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.benchmark import Benchmark  # noqa: F401
from app.models.document import Document  # noqa: F401
from app.models.etalon import Etalon  # noqa: F401
from app.models.feedback import Feedback  # noqa: F401
from app.models.provider_key import ProviderKey  # noqa: F401
from app.models.skill import Skill  # noqa: F401
from app.models.user import User  # noqa: F401

__all__ = ["Base"]
