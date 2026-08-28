from collections.abc import Iterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session, sessionmaker

from meet_scheduler.availability.router import create_availability_router
from meet_scheduler.bookings.router import create_bookings_router
from meet_scheduler.bookings.service import BookingError
from meet_scheduler.config import Settings, get_settings
from meet_scheduler.database import create_session_factory, session_scope
from meet_scheduler.hosts.auth import create_auth_router
from meet_scheduler.hosts.profile import create_profile_router
from meet_scheduler.meeting_types.router import create_meeting_type_router
from meet_scheduler.public.router import create_public_router


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    app = FastAPI(title="Meet Scheduler API")

    @app.exception_handler(BookingError)
    async def handle_booking_error(
        request: Request, exc: BookingError  # noqa: ARG001
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message, "details": []},
        )

    # PRD 171-172 requires a consistent {code, message, details} envelope.
    # Intentionally global: auth/profile/meeting-type errors were migrated
    # to this envelope (see tests/auth/test_*.py). BookingError is separate
    # so booking-specific codes (slot_no_longer_available etc.) keep 409.
    @app.exception_handler(HTTPException)
    async def handle_http_error(
        request: Request, exc: HTTPException  # noqa: ARG001
    ) -> JSONResponse:
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", "request_error"))
            message = str(exc.detail.get("message", "The request failed."))
        else:
            code = {
                401: "unauthenticated",
                403: "unauthorized",
                404: "not_found",
                409: "conflict",
                422: "validation_error",
            }.get(exc.status_code, "request_error")
            message = str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": code, "message": message, "details": []},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError  # noqa: ARG001
    ) -> JSONResponse:
        details = [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "The request is invalid.",
                "details": details,
            },
        )

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
    app.include_router(create_meeting_type_router(get_session, resolve_settings))
    app.include_router(create_availability_router(get_session, resolve_settings))
    app.include_router(create_bookings_router(get_session, resolve_settings))
    app.include_router(create_public_router(get_session, resolve_settings))

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
