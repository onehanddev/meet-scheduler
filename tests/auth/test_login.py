import jwt
from fastapi.testclient import TestClient


def test_registered_host_can_log_in(client: TestClient) -> None:
    register_response = client.post(
        "/auth/register",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert register_response.status_code == 201

    login_response = client.post(
        "/auth/login",
        json={
            "email": "HOST@example.com",
            "password": "correct horse battery staple",
        },
    )

    assert login_response.status_code == 200
    body = login_response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900
    assert len(body["access_token"].split(".")) == 3
    assert len(body["refresh_token"].split(".")) == 3


def test_login_rejects_wrong_password_without_revealing_account_existence(
    client: TestClient,
) -> None:
    register_response = client.post(
        "/auth/register",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert register_response.status_code == 201

    response = client.post(
        "/auth/login",
        json={
            "email": "host@example.com",
            "password": "wrong horse battery staple",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_login_rejects_unknown_email_with_the_same_invalid_credentials_response(
    client: TestClient,
) -> None:
    response = client.post(
        "/auth/login",
        json={
            "email": "missing@example.com",
            "password": "correct horse battery staple",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid email or password"}


def test_login_returns_jwts_with_expected_host_claims(client: TestClient) -> None:
    register_response = client.post(
        "/auth/register",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert register_response.status_code == 201
    host_id = register_response.json()["id"]

    login_response = client.post(
        "/auth/login",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert login_response.status_code == 200

    body = login_response.json()
    access_claims = jwt.decode(
        body["access_token"],
        "test-token-secret-that-is-long-enough",
        algorithms=["HS256"],
    )
    refresh_claims = jwt.decode(
        body["refresh_token"],
        "test-token-secret-that-is-long-enough",
        algorithms=["HS256"],
    )

    assert access_claims["sub"] == host_id
    assert access_claims["type"] == "access"
    assert access_claims["exp"] - access_claims["iat"] == 900
    assert isinstance(access_claims["jti"], str)
    assert refresh_claims["sub"] == host_id
    assert refresh_claims["type"] == "refresh"
    assert refresh_claims["exp"] - refresh_claims["iat"] == 30 * 24 * 60 * 60
    assert isinstance(refresh_claims["jti"], str)
    assert access_claims["jti"] != refresh_claims["jti"]
