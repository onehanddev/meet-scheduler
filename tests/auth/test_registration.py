from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from meet_scheduler.models import Host


def test_prospective_host_can_register(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={
            "email": "NewHost@Example.com",
            "password": "correct horse battery staple",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert body["email"] == "newhost@example.com"
    assert "password" not in body
    assert "password_hash" not in body


def test_registration_stores_only_an_argon2id_password_hash(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    password = "correct horse battery staple"

    response = client.post(
        "/auth/register",
        json={"email": "newhost@example.com", "password": password},
    )

    assert response.status_code == 201
    with session_factory() as session:
        password_hash = session.scalar(select(Host.password_hash))
    assert password_hash is not None
    assert password_hash.startswith("$argon2id$")
    assert password_hash != password


def test_registration_rejects_an_existing_email_case_insensitively(
    client: TestClient,
) -> None:
    first_response = client.post(
        "/auth/register",
        json={
            "email": "newhost@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert first_response.status_code == 201

    duplicate_response = client.post(
        "/auth/register",
        json={
            "email": "NewHost@Example.com",
            "password": "another secure password",
        },
    )

    assert duplicate_response.status_code == 409
    assert duplicate_response.json() == {
        "code": "conflict",
        "message": "An account with this email already exists",
        "details": [],
    }


def test_registration_rejects_an_invalid_email(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={
            "email": "not-an-email",
            "password": "correct horse battery staple",
        },
    )

    assert response.status_code == 422
