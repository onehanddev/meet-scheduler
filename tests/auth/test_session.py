from fastapi.testclient import TestClient


def test_authenticated_host_can_fetch_own_profile(client: TestClient) -> None:
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
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]

    me_response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert me_response.status_code == 200
    body = me_response.json()
    assert body["email"] == "host@example.com"
    assert body["id"] == register_response.json()["id"]
    assert "password" not in body
    assert "password_hash" not in body


def test_me_rejects_missing_access_token(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json() == {
        "code": "unauthenticated",
        "message": "Not authenticated",
        "details": [],
    }


def test_me_rejects_refresh_token_as_access_token(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    login_response = client.post(
        "/auth/login",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    refresh_token = login_response.json()["refresh_token"]

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )

    assert response.status_code == 401


def test_refresh_rotates_credentials_and_rejects_replay(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    login_response = client.post(
        "/auth/login",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    refresh_token = login_response.json()["refresh_token"]

    refresh_response = client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert refresh_response.status_code == 200
    new_body = refresh_response.json()
    assert new_body["token_type"] == "bearer"
    assert new_body["access_token"] != login_response.json()["access_token"]
    assert new_body["refresh_token"] != refresh_token

    # new access token must work
    me_response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {new_body['access_token']}"},
    )
    assert me_response.status_code == 200

    # replay of old refresh token must be rejected
    replay_response = client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert replay_response.status_code == 401


def test_refresh_rejects_access_token(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    login_response = client.post(
        "/auth/login",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    access_token = login_response.json()["access_token"]

    response = client.post(
        "/auth/refresh",
        json={"refresh_token": access_token},
    )

    assert response.status_code == 401


def test_logout_revokes_refresh_token_and_rejects_further_use(  # noqa: E501
    client: TestClient,
) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    login_response = client.post(
        "/auth/login",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    refresh_token = login_response.json()["refresh_token"]

    logout_response = client.post(
        "/auth/logout",
        json={"refresh_token": refresh_token},
    )

    assert logout_response.status_code == 204

    refresh_response = client.post(
        "/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert refresh_response.status_code == 401

    second_logout = client.post(
        "/auth/logout",
        json={"refresh_token": refresh_token},
    )

    assert second_logout.status_code == 401


def test_logout_rejects_access_token(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    login_response = client.post(
        "/auth/login",
        json={
            "email": "host@example.com",
            "password": "correct horse battery staple",
        },
    )
    access_token = login_response.json()["access_token"]

    response = client.post(
        "/auth/logout",
        json={"refresh_token": access_token},
    )

    assert response.status_code == 401


def test_cross_host_refresh_is_rejected(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={
            "email": "alice@example.com",
            "password": "correct horse battery staple",
        },
    )
    client.post(
        "/auth/register",
        json={
            "email": "bob@example.com",
            "password": "correct horse battery staple",
        },
    )
    alice_login = client.post(
        "/auth/login",
        json={
            "email": "alice@example.com",
            "password": "correct horse battery staple",
        },
    )
    bob_login = client.post(
        "/auth/login",
        json={
            "email": "bob@example.com",
            "password": "correct horse battery staple",
        },
    )
    # Bob's token must not be usable to affect Alice's session; each token is host-bound
    alice_refresh = alice_login.json()["refresh_token"]
    bob_refresh = bob_login.json()["refresh_token"]

    # Alice refresh should succeed with her own token
    alice_refresh_response = client.post(
        "/auth/refresh",
        json={"refresh_token": alice_refresh},
    )
    assert alice_refresh_response.status_code == 200

    # Bob's original refresh still works, but Alice's old one is now revoked
    replay = client.post(
        "/auth/refresh",
        json={"refresh_token": alice_refresh},
    )
    assert replay.status_code == 401

    # Bob's refresh works independently
    bob_refresh_response = client.post(
        "/auth/refresh",
        json={"refresh_token": bob_refresh},
    )
    assert bob_refresh_response.status_code == 200
