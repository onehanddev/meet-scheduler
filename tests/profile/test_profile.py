from fastapi.testclient import TestClient


def _register_and_login(client: TestClient, email: str = "host@example.com") -> str:
    client.post(
        "/auth/register",
        json={"email": email, "password": "correct horse battery staple"},
    )
    resp = client.post(
        "/auth/login",
        json={"email": email, "password": "correct horse battery staple"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_get_me_returns_profile_fields_and_no_leakage(client: TestClient) -> None:
    token = _register_and_login(client)
    resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert "id" in body
    assert "email" in body
    assert body["email"] == "host@example.com"
    assert "username" in body
    assert "display_name" in body
    assert "timezone" in body
    assert "password_hash" not in body
    assert "password" not in body
    assert "token" not in str(body).lower()


def test_put_me_persists_and_returns_profile(client: TestClient) -> None:
    token = _register_and_login(client)
    resp = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "username": "alice-wonder",
            "display_name": "Alice Wonder",
            "timezone": "Asia/Kolkata",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice-wonder"
    assert body["display_name"] == "Alice Wonder"
    assert body["timezone"] == "Asia/Kolkata"

    # GET round-trips
    get_resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert get_resp.status_code == 200
    assert get_resp.json()["username"] == "alice-wonder"
    assert get_resp.json()["display_name"] == "Alice Wonder"
    assert get_resp.json()["timezone"] == "Asia/Kolkata"


def test_username_is_normalized_to_lowercase(client: TestClient) -> None:
    token = _register_and_login(client)
    resp = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "AliceWonder"},
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "alicewonder"


def test_username_rejects_url_unsafe_characters(client: TestClient) -> None:
    token = _register_and_login(client)
    resp = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "alice wonder"},
    )
    assert resp.status_code == 422

    resp2 = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "alice@wonder"},
    )
    assert resp2.status_code == 422


def test_username_rejects_reserved_names(client: TestClient) -> None:
    token = _register_and_login(client)
    for reserved in ["auth", "me", "healthz", "docs", "api"]:
        resp = client.put(
            "/me",
            headers={"Authorization": f"Bearer {token}"},
            json={"username": reserved},
        )
        assert resp.status_code == 422, f"reserved {reserved} should be 422"


def test_username_enforces_case_insensitive_uniqueness_409(client: TestClient) -> None:
    token_alice = _register_and_login(client, email="alice@example.com")
    token_bob = _register_and_login(client, email="bob@example.com")

    resp = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token_alice}"},
        json={"username": "alice-wonder"},
    )
    assert resp.status_code == 200

    # Bob tries same username different case
    dup = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token_bob}"},
        json={"username": "Alice-Wonder"},
    )
    assert dup.status_code == 409
    assert dup.json()["detail"] == "Username already taken"


def test_can_change_username(client: TestClient) -> None:
    token = _register_and_login(client)
    r1 = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "first-name"},
    )
    assert r1.status_code == 200
    assert r1.json()["username"] == "first-name"

    r2 = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "second-name"},
    )
    assert r2.status_code == 200
    assert r2.json()["username"] == "second-name"

    # Old username becomes available
    token_other = _register_and_login(client, email="other@example.com")
    r3 = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token_other}"},
        json={"username": "first-name"},
    )
    assert r3.status_code == 200


def test_display_name_round_trips(client: TestClient) -> None:
    token = _register_and_login(client)
    resp = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"display_name": "Alice Wonderland"},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Alice Wonderland"


def test_timezone_must_be_valid_iana(client: TestClient) -> None:
    token = _register_and_login(client)
    resp = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"timezone": "Invalid/Timezone"},
    )
    assert resp.status_code == 422

    resp2 = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"timezone": "Asia/Kolkata"},
    )
    assert resp2.status_code == 200
    assert resp2.json()["timezone"] == "Asia/Kolkata"

    resp3 = client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"timezone": "UTC"},
    )
    assert resp3.status_code == 200


def test_get_me_returns_401_when_missing_token(client: TestClient) -> None:
    resp = client.get("/me")
    assert resp.status_code == 401

    resp2 = client.put("/me", json={"display_name": "Foo"})
    assert resp2.status_code == 401


def test_put_me_returns_401_with_invalid_token(client: TestClient) -> None:
    resp = client.put(
        "/me",
        headers={"Authorization": "Bearer invalid.token.here"},
        json={"display_name": "Foo"},
    )
    assert resp.status_code == 401


def test_put_me_rejects_refresh_token(client: TestClient) -> None:
    client.post(
        "/auth/register",
        json={"email": "host@example.com", "password": "correct horse battery staple"},
    )
    login = client.post(
        "/auth/login",
        json={"email": "host@example.com", "password": "correct horse battery staple"},
    )
    refresh = login.json()["refresh_token"]
    resp = client.put(
        "/me",
        headers={"Authorization": f"Bearer {refresh}"},
        json={"display_name": "Foo"},
    )
    assert resp.status_code == 401


def test_cross_host_isolation(client: TestClient) -> None:
    # Each host only sees own profile
    token_alice = _register_and_login(client, email="alice@example.com")
    token_bob = _register_and_login(client, email="bob@example.com")

    client.put(
        "/me",
        headers={"Authorization": f"Bearer {token_alice}"},
        json={"username": "alice123", "display_name": "Alice"},
    )
    client.put(
        "/me",
        headers={"Authorization": f"Bearer {token_bob}"},
        json={"username": "bob123", "display_name": "Bob"},
    )

    alice_me = client.get("/me", headers={"Authorization": f"Bearer {token_alice}"})
    bob_me = client.get("/me", headers={"Authorization": f"Bearer {token_bob}"})

    assert alice_me.json()["username"] == "alice123"
    assert alice_me.json()["display_name"] == "Alice"
    assert bob_me.json()["username"] == "bob123"
    assert bob_me.json()["display_name"] == "Bob"


def test_auth_me_also_returns_profile_fields(client: TestClient) -> None:
    token = _register_and_login(client)
    client.put(
        "/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"username": "alice123", "display_name": "Alice", "timezone": "UTC"},
    )
    resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "alice123"
    assert body["display_name"] == "Alice"
    assert body["timezone"] == "UTC"
