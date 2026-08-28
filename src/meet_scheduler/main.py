from collections.abc import Iterator

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from meet_scheduler.auth import create_auth_router
from meet_scheduler.config import Settings, get_settings
from meet_scheduler.database import create_session_factory, session_scope
from meet_scheduler.profile import create_profile_router


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    app = FastAPI(title="Meet Scheduler API")

    def resolve_settings() -> Settings:
        return settings or get_settings()

    def get_session() -> Iterator[Session]:
        active_settings = resolve_settings()
        active_factory = session_factory or create_session_factory(
            active_settings.database_url
        )
        yield from session_scope(active_factory)

    app.include_router(create_auth_router(get_session, resolve_settings))
    app.include_router(create_profile_router(get_session, resolve_settings))

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
