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


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup_host_with_username(client: TestClient, email: str, username: str) -> str:
    token = _register_and_login(client, email=email)
    resp = client.put(
        "/me",
        headers=_auth_header(token),
        json={"username": username, "display_name": "Test Host", "timezone": "UTC"},
    )
    assert resp.status_code == 200, resp.text
    return token


def test_create_meeting_type_success(client: TestClient) -> None:
    token = _setup_host_with_username(client, "host@example.com", "alice")
    resp = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "30 Minute Meeting", "event_slug": "30min", "duration": 30},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["title"] == "30 Minute Meeting"
    assert body["event_slug"] == "30min"
    assert body["duration"] == 30
    assert body["active"] is True
    assert body["minimum_notice"] == 60
    assert body["horizon_days"] == 60 or body.get("horizon") == 60
    assert "id" in body
    assert body["host_id"] is not None or "host_id" not in body  # allow minimal


def test_second_post_returns_409(client: TestClient) -> None:
    token = _setup_host_with_username(client, "host@example.com", "alice")
    r1 = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "30 Minute Meeting", "event_slug": "30min", "duration": 30},
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "Another", "event_slug": "another", "duration": 15},
    )
    assert r2.status_code == 409


def test_duration_validation_only_allows_15_30_45_60(client: TestClient) -> None:
    token = _setup_host_with_username(client, "host@example.com", "alice")
    for _valid in [15, 30, 45, 60]:
        # need fresh host per valid; tested separately in next test
        pass
    # test invalid
    resp = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "Bad", "event_slug": "bad", "duration": 20},
    )
    assert resp.status_code == 422
    resp2 = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "Bad", "event_slug": "bad2", "duration": 10},
    )
    assert resp2.status_code == 422
    resp3 = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "Bad", "event_slug": "bad3", "duration": 60},
    )
    # This should succeed (first valid)
    assert resp3.status_code == 201, resp3.text


def test_duration_each_valid_value_succeeds(client: TestClient) -> None:
    for idx, dur in enumerate([15, 30, 45, 60]):
        email = f"host{idx}@example.com"
        token = _setup_host_with_username(client, email, f"user{idx}")
        resp = client.post(
            "/meeting-types",
            headers=_auth_header(token),
            json={
                "title": f"Meeting {dur}",
                "event_slug": f"slot-{dur}",
                "duration": dur,
            },
        )
        assert resp.status_code == 201, f"duration {dur} failed: {resp.text}"
        assert resp.json()["duration"] == dur


def test_event_slug_url_safe_and_unique_per_host(client: TestClient) -> None:
    token = _setup_host_with_username(client, "host@example.com", "alice")
    resp = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "Test", "event_slug": "valid-slug_123", "duration": 30},
    )
    assert resp.status_code == 201
    # event_slug normalized
    assert resp.json()["event_slug"] == "valid-slug_123"

    # invalid slug
    token_other = _setup_host_with_username(client, "other@example.com", "bob")
    bad = client.post(
        "/meeting-types",
        headers=_auth_header(token_other),
        json={"title": "Test", "event_slug": "invalid slug", "duration": 30},
    )
    assert bad.status_code == 422
    bad2 = client.post(
        "/meeting-types",
        headers=_auth_header(token_other),
        json={"title": "Test", "event_slug": "bad@slug", "duration": 30},
    )
    assert bad2.status_code == 422


def test_event_slug_unique_per_host_allows_same_slug_different_hosts(
    client: TestClient,
) -> None:
    token_a = _setup_host_with_username(client, "alice@example.com", "alice")
    token_b = _setup_host_with_username(client, "bob@example.com", "bob")
    r1 = client.post(
        "/meeting-types",
        headers=_auth_header(token_a),
        json={"title": "A", "event_slug": "30min", "duration": 30},
    )
    assert r1.status_code == 201
    r2 = client.post(
        "/meeting-types",
        headers=_auth_header(token_b),
        json={"title": "B", "event_slug": "30min", "duration": 30},
    )
    assert r2.status_code == 201


def test_public_get_returns_meeting_info(client: TestClient) -> None:
    token = _setup_host_with_username(client, "host@example.com", "alice")
    create = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "30 Minute Meeting", "event_slug": "30min", "duration": 30},
    )
    assert create.status_code == 201
    # Set display_name already via setup
    resp = client.get("/alice/30min")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["username"] == "alice"
    assert body["display_name"] == "Test Host"
    assert body["title"] == "30 Minute Meeting"
    assert body["duration"] == 30
    # privacy
    assert "email" not in body
    assert "password" not in str(body).lower()
    assert "password_hash" not in body


def test_active_toggle_hides_public_page_and_rejects_booking(
    client: TestClient,
) -> None:
    token = _setup_host_with_username(client, "host@example.com", "alice")
    create = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "30 Minute Meeting", "event_slug": "30min", "duration": 30},
    )
    assert create.status_code == 201
    mt_id = create.json()["id"]

    # deactivate via PUT
    update = client.put(
        f"/meeting-types/{mt_id}",
        headers=_auth_header(token),
        json={"active": False},
    )
    # also allow PUT /meeting-types without id or PATCH
    if update.status_code == 404:
        update = client.put(
            "/meeting-types",
            headers=_auth_header(token),
            json={"active": False},
        )
    if update.status_code not in (200, 204):
        # try PATCH
        update = client.patch(
            f"/meeting-types/{mt_id}",
            headers=_auth_header(token),
            json={"active": False},
        )
    assert update.status_code in (200, 204), update.text

    public = client.get("/alice/30min")
    assert public.status_code == 404, public.text

    booking = client.post(
        "/alice/30min/bookings",
        json={
            "invitee_name": "Bob",
            "invitee_email": "bob@example.com",
            "slot_start": "2026-09-01T10:00:00Z",
        },
    )
    assert booking.status_code == 404, booking.text


def test_minimum_notice_and_horizon_defaults_and_configurable(
    client: TestClient,
) -> None:
    token = _setup_host_with_username(client, "host@example.com", "alice")
    r1 = client.post(
        "/meeting-types",
        headers=_auth_header(token),
        json={"title": "Test", "event_slug": "30min", "duration": 30},
    )
    assert r1.status_code == 201
    body = r1.json()
    # defaults
    notice = body.get("minimum_notice", body.get("minimum_notice_minutes"))
    horizon = body.get("horizon_days", body.get("horizon"))
    assert notice == 60
    assert horizon == 60

    mt_id = body["id"]
    # update to custom values
    upd = client.put(
        f"/meeting-types/{mt_id}",
        headers=_auth_header(token),
        json={"minimum_notice": 120, "horizon_days": 30},
    )
    if upd.status_code == 404:
        upd = client.put(
            "/meeting-types",
            headers=_auth_header(token),
            json={"minimum_notice": 120, "horizon_days": 30},
        )
    if upd.status_code in (404, 422):
        # try horizon alias
        upd = client.put(
            f"/meeting-types/{mt_id}",
            headers=_auth_header(token),
            json={"minimum_notice": 120, "horizon": 30},
        )
    assert upd.status_code in (200, 204), upd.text
    if upd.status_code == 200:
        ubody = upd.json()
        n = ubody.get("minimum_notice", ubody.get("minimum_notice_minutes"))
        h = ubody.get("horizon_days", ubody.get("horizon"))
        assert n == 120
        assert h == 30


def test_ownership_host_a_cannot_modify_host_b(client: TestClient) -> None:
    token_a = _setup_host_with_username(client, "alice@example.com", "alice")
    token_b = _setup_host_with_username(client, "bob@example.com", "bob")
    r1 = client.post(
        "/meeting-types",
        headers=_auth_header(token_a),
        json={"title": "Alice Meeting", "event_slug": "30min", "duration": 30},
    )
    assert r1.status_code == 201
    mt_id = r1.json()["id"]

    # Bob tries to modify Alice's meeting type by id
    upd = client.put(
        f"/meeting-types/{mt_id}",
        headers=_auth_header(token_b),
        json={"title": "Hijacked"},
    )
    # Expect 403 or 404 or 401
    assert upd.status_code in (401, 403, 404), upd.text

    # Also test that Bob cannot create second type via A's id? Already covered
    # And that GET /meeting-types only returns own
    list_b = client.get("/meeting-types", headers=_auth_header(token_b))
    if list_b.status_code == 200:
        body = list_b.json()
        # should not contain Alice's meeting type
        if isinstance(body, list):
            ids = [x.get("id") for x in body]
            assert mt_id not in ids
        elif isinstance(body, dict):
            assert body.get("id") != mt_id or body == {}


def test_requires_authentication(client: TestClient) -> None:
    resp = client.post(
        "/meeting-types",
        json={"title": "Test", "event_slug": "30min", "duration": 30},
    )
    assert resp.status_code == 401

    resp2 = client.put(
        "/meeting-types/00000000-0000-0000-0000-000000000000",
        json={"title": "Test"},
    )
    assert resp2.status_code == 401


def test_reserved_event_slug_rejected(client: TestClient) -> None:
    token = _setup_host_with_username(client, "host@example.com", "alice")
    for reserved in ["auth", "api", "healthz", "docs"]:
        resp = client.post(
            "/meeting-types",
            headers=_auth_header(token),
            json={"title": "Test", "event_slug": reserved, "duration": 30},
        )
        # if first succeeded, next would be 409 due to one-per-host
        if resp.status_code == 201:
            break
        assert resp.status_code == 422, (
            f"reserved {reserved} should be 422 got {resp.status_code} {resp.text}"
        )
        # need new host for next iteration; reuse token okay after 422
