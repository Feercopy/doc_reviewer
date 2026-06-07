from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import admin_users, analyses, auth, documents, feedback, provider_settings, skills


def create_app() -> FastAPI:
    api = FastAPI(title="Gate Challenger Service API")

    api.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @api.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    api.include_router(auth.router)
    api.include_router(admin_users.router)
    api.include_router(provider_settings.router)
    api.include_router(skills.router)
    api.include_router(skills.admin_router)
    api.include_router(analyses.router)
    api.include_router(feedback.router)
    api.include_router(documents.router)
    return api


app = create_app()
