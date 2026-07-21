from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import cors_allow_origins
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
    api.include_router(admin_users.router)
    api.include_router(admin_documents.router)
    api.include_router(admin_analyses.router)
    api.include_router(admin_etalons.router)
    api.include_router(admin_benchmarks.router)
    api.include_router(admin_feedback.router)
    api.include_router(provider_settings.router)
    api.include_router(skills.router)
    api.include_router(skills.admin_router)
    api.include_router(analyses.router)
    api.include_router(ic_review.router)
    api.include_router(etalons.router)
    api.include_router(benchmarks.router)
    api.include_router(feedback.router)
    api.include_router(documents.router)
    return api


app = create_app()
