import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from meet_scheduler.config import Settings
from meet_scheduler.main import create_app

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://localhost/meet_scheduler_test",
)
PROJECT_ROOT = Path(__file__).parents[1]


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    if make_url(TEST_DATABASE_URL).database != "meet_scheduler_test":
        raise RuntimeError("Tests must run against the meet_scheduler_test database")

    engine = create_engine(TEST_DATABASE_URL)
    alembic_config = Config(PROJECT_ROOT / "alembic.ini")
    alembic_config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    yield factory

    command.downgrade(alembic_config, "base")
    engine.dispose()


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> TestClient:
    settings = Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        token_secret="test-token-secret-that-is-long-enough",
    )
    return TestClient(create_app(settings=settings, session_factory=session_factory))
