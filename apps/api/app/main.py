from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import admin_users, auth


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
    return api


app = create_app()
