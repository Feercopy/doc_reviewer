from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import cors_allow_origins
from app.dependencies.auth import require_admin_when_external_access_disabled
from app.logging import RequestIdMiddleware
from app.routers import (
    admin_analyses,
    admin_benchmarks,
    admin_documents,
    admin_etalons,
    admin_feedback,
    admin_users,
    analyses,
    auth,
    benchmarks,
    documents,
    etalons,
    feedback,
    ic_review,
    provider_settings,
    skills,
)


def create_app() -> FastAPI:
    api = FastAPI(title="Gate Challenger Service API")

    api.add_middleware(RequestIdMiddleware)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=cors_allow_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_private_network=True,
    )

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    api.include_router(auth.router)
    private_access = [Depends(require_admin_when_external_access_disabled)]
    for router in (
        admin_users.router,
        admin_documents.router,
        admin_analyses.router,
        admin_etalons.router,
        admin_benchmarks.router,
        admin_feedback.router,
        provider_settings.router,
        skills.router,
        skills.admin_router,
        analyses.router,
        ic_review.router,
        etalons.router,
        benchmarks.router,
        feedback.router,
        documents.router,
    ):
        api.include_router(router, dependencies=private_access)
    return api


app = create_app()
