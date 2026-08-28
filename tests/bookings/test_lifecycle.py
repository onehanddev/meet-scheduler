"""TDD for Issue #6 — booking lifecycle: list / cancel / reschedule.

Seams under test:
  - Authenticated host: GET /bookings?status=&from=&to=, GET /bookings/{id}
  - Invitee token: POST /bookings/{id}/cancel, POST /bookings/{id}/reschedule

These are the public HTTP seams per PRD 165/168. Tests verify externally
observable behavior via FastAPI TestClient.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from meet_scheduler.bookings.models import Booking


def _register_host(client: TestClient, email: str, username: str) -> str:
    password = "correct horse battery staple"
    assert client.post(
        "/auth/register", json={"email": email, "password": password}
    ).status_code == 201
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.put(
        "/me",
        headers=headers,
        json={
            "username": username,
            "display_name": username.title(),
            "timezone": "UTC",
        },
    ).status_code == 200
    assert client.post(
        "/meeting-types",
        headers=headers,
        json={"title": "Thirty", "event_slug": "30min", "duration": 30, "active": True},
    ).status_code == 201
    assert client.put(
        "/availability",
        headers=headers,
        json={"windows": [{"weekday": 0, "start": "09:00", "end": "12:00"}]},
    ).status_code == 200
    return token


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _book_slot(
    client: TestClient, at: str = "2026-08-31T09:00:00Z", invitee: str = "Bob"
) -> tuple[str, str]:
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        resp = client.post(
            "/alice/30min/bookings",
            json={
                "invitee_name": invitee,
                "invitee_email": f"{invitee.lower()}@example.com",
                "slot_start": at,
            },
        )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body["id"], body["management_token"]


def test_host_lists_only_own_bookings_and_filters(client: TestClient) -> None:
    token_alice = _register_host(client, "alice@example.com", "alice")
    token_bob_host = _register_host(client, "bobhost@example.com", "bobhost")
    booking_id_a, _ = _book_slot(client, "2026-08-31T09:00:00Z", "InviteeA")
    _book_slot(client, "2026-08-31T09:30:00Z", "InviteeB")
    # Unauthenticated → 401
    resp = client.get("/bookings")
    assert resp.status_code == 401
    # Other host sees no bookings
    resp = client.get("/bookings", headers=_auth_headers(token_bob_host))
    assert resp.status_code == 200
    assert resp.json() == []
    # Owner sees own bookings
    resp = client.get("/bookings", headers=_auth_headers(token_alice))
    assert resp.status_code == 200
    bookings = resp.json()
    ids = {b["id"] for b in bookings}
    assert booking_id_a in ids


def test_cancelled_remains_queryable_and_status_filter(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    token = _register_host(client, "host2@example.com", "alice2")
    # Override alice name for this test: use alice2 host
    # Book via alice2
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        resp = client.post(
            "/alice2/30min/bookings",
            json={
                "invitee_name": "Carol",
                "invitee_email": "carol@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
    assert resp.status_code == 201
    bid = resp.json()["id"]
    mgmt = resp.json()["management_token"]
    # Cancel
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        c_resp = client.post(f"/bookings/{bid}/cancel", json={"management_token": mgmt})
    assert c_resp.status_code == 200
    assert c_resp.json()["status"] == "cancelled"
    headers = _auth_headers(token)
    # List cancelled
    resp = client.get("/bookings?status=cancelled", headers=headers)
    assert resp.status_code == 200
    assert any(b["id"] == bid for b in resp.json())
    # List confirmed should not contain cancelled
    resp = client.get("/bookings?status=confirmed", headers=headers)
    assert resp.status_code == 200
    assert all(b["id"] != bid for b in resp.json())
    # Detail retrieval
    resp = client.get(f"/bookings/{bid}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_get_booking_requires_owner_and_auth(client: TestClient) -> None:
    token_alice = _register_host(client, "alice3@example.com", "alice3")
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        resp = client.post(
            "/alice3/30min/bookings",
            json={
                "invitee_name": "Dave",
                "invitee_email": "dave@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
    bid = resp.json()["id"]
    # No auth
    assert client.get(f"/bookings/{bid}").status_code == 401
    # Wrong host
    token_other = _register_host(client, "other@example.com", "otherhost")
    resp = client.get(f"/bookings/{bid}", headers=_auth_headers(token_other))
    assert resp.status_code == 404
    # Correct host succeeds
    resp = client.get(f"/bookings/{bid}", headers=_auth_headers(token_alice))
    assert resp.status_code == 200


def test_cancel_idempotent_and_invalid_token(client: TestClient) -> None:
    _register_host(client, "alice4@example.com", "alice4")
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        resp = client.post(
            "/alice4/30min/bookings",
            json={
                "invitee_name": "Eve",
                "invitee_email": "eve@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
    bid = resp.json()["id"]
    mgmt = resp.json()["management_token"]
    # Invalid token → 401
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        bad = client.post(
            f"/bookings/{bid}/cancel", json={"management_token": "bad-token"}
        )
    assert bad.status_code == 401
    assert bad.json()["code"] == "invalid_management_token"
    # Valid cancel
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        ok = client.post(f"/bookings/{bid}/cancel", json={"management_token": mgmt})
    assert ok.status_code == 200
    assert ok.json()["status"] == "cancelled"
    # Idempotent second cancel → same
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        again = client.post(f"/bookings/{bid}/cancel", json={"management_token": mgmt})
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"


def test_freed_interval_becomes_rebookable(client: TestClient) -> None:
    _register_host(client, "alice5@example.com", "alice5")
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        resp = client.post(
            "/alice5/30min/bookings",
            json={
                "invitee_name": "Frank",
                "invitee_email": "frank@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
    bid = resp.json()["id"]
    mgmt = resp.json()["management_token"]
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        client.post(f"/bookings/{bid}/cancel", json={"management_token": mgmt})
    # Re-book same slot should succeed when still valid
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        resp2 = client.post(
            "/alice5/30min/bookings",
            json={
                "invitee_name": "Grace",
                "invitee_email": "grace@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
    assert resp2.status_code == 201, resp2.text
    assert resp2.json()["status"] == "confirmed"


def test_reschedule_atomically_swaps_and_history_link(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register_host(client, "alice6@example.com", "alice6")
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        resp = client.post(
            "/alice6/30min/bookings",
            json={
                "invitee_name": "Heidi",
                "invitee_email": "heidi@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
    bid = resp.json()["id"]
    mgmt = resp.json()["management_token"]
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        r_resp = client.post(
            f"/bookings/{bid}/reschedule",
            json={"management_token": mgmt, "new_slot_start": "2026-08-31T09:30:00Z"},
        )
    assert r_resp.status_code == 200, r_resp.text
    new_body = r_resp.json()
    new_id = new_body["id"]
    assert new_id != bid
    assert new_body["status"] == "confirmed"
    # Compare as UTC instants regardless of serialisation offset
    new_start = datetime.fromisoformat(new_body["start_time"].replace("Z", "+00:00"))
    assert new_start.astimezone(UTC) == datetime(2026, 8, 31, 9, 30, tzinfo=UTC)
    assert new_body["predecessor_id"] == bid
    # Old booking should be cancelled but still queryable
    with session_factory() as s:
        old = s.get(Booking, bid)
        assert old is not None
        assert old.status == "cancelled"
        new = s.get(Booking, new_id)
        assert new is not None
        assert new.predecessor_id == old.id
        assert new.status == "confirmed"


def test_reschedule_rejects_same_interval_and_invalid_slot(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register_host(client, "alice7@example.com", "alice7")
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        resp = client.post(
            "/alice7/30min/bookings",
            json={
                "invitee_name": "Ivan",
                "invitee_email": "ivan@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
    bid = resp.json()["id"]
    mgmt = resp.json()["management_token"]
    # Same interval → 409
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        same = client.post(
            f"/bookings/{bid}/reschedule",
            json={"management_token": mgmt, "new_slot_start": "2026-08-31T09:00:00Z"},
        )
    assert same.status_code == 409
    assert same.json()["code"] == "reschedule_same_interval"
    # Ensure old still confirmed after failure
    with session_factory() as s:
        assert s.get(Booking, bid).status == "confirmed"  # type: ignore[union-attr]
    # Invalid slot (outside availability) → 409
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        invalid = client.post(
            f"/bookings/{bid}/reschedule",
            json={"management_token": mgmt, "new_slot_start": "2026-08-31T09:15:00Z"},
        )
    assert invalid.status_code == 409
    assert invalid.json()["code"] == "slot_no_longer_available"
    with session_factory() as s:
        assert s.get(Booking, bid).status == "confirmed"  # type: ignore[union-attr]


def test_reschedule_token_scoping_prevents_cross_use(client: TestClient) -> None:  # noqa: E501
    _register_host(client, "alice8@example.com", "alice8")
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        r1 = client.post(
            "/alice8/30min/bookings",
            json={
                "invitee_name": "A",
                "invitee_email": "a@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
        r2 = client.post(
            "/alice8/30min/bookings",
            json={
                "invitee_name": "B",
                "invitee_email": "b@example.com",
                "slot_start": "2026-08-31T09:30:00Z",
            },
        )
    bid1 = r1.json()["id"]
    mgmt1 = r1.json()["management_token"]
    bid2 = r2.json()["id"]
    # Cross-token must not work
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        bad_cancel = client.post(
            f"/bookings/{bid2}/cancel", json={"management_token": mgmt1}
        )
    assert bad_cancel.status_code == 401
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        bad_res = client.post(
            f"/bookings/{bid2}/reschedule",
            json={"management_token": mgmt1, "new_slot_start": "2026-08-31T10:00:00Z"},
        )
    assert bad_res.status_code == 401
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        bad_cancel2 = client.post(
            f"/bookings/{bid1}/cancel",
            json={"management_token": r2.json()["management_token"]},
        )
    assert bad_cancel2.status_code == 401


def test_no_confirmed_overlap_across_reschedule_race(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _register_host(client, "alice9@example.com", "alice9")
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    # Create two bookings at different times
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        r1 = client.post(
            "/alice9/30min/bookings",
            json={
                "invitee_name": "A",
                "invitee_email": "a@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
        r2 = client.post(
            "/alice9/30min/bookings",
            json={
                "invitee_name": "B",
                "invitee_email": "b@example.com",
                "slot_start": "2026-08-31T10:00:00Z",
            },
        )
    bid1 = r1.json()["id"]
    mgmt1 = r1.json()["management_token"]
    bid2 = r2.json()["id"]
    mgmt2 = r2.json()["management_token"]
    # Both try to reschedule to 09:30 concurrently (free slot) — only one should win
    target = "2026-08-31T09:30:00Z"
    barrier = Barrier(2)

    def reschedule1() -> int:
        barrier.wait()
        with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
            resp = client.post(
                f"/bookings/{bid1}/reschedule",
                json={"management_token": mgmt1, "new_slot_start": target},
            )
            return resp.status_code

    def reschedule2() -> int:
        barrier.wait()
        with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
            resp = client.post(
                f"/bookings/{bid2}/reschedule",
                json={"management_token": mgmt2, "new_slot_start": target},
            )
            return resp.status_code

    with ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(reschedule1)
        f2 = ex.submit(reschedule2)
        s1 = f1.result()
        s2 = f2.result()
    assert sorted([s1, s2]) == [200, 409], (s1, s2)
    with session_factory() as s:
        confirmed = s.scalars(
            select(Booking).where(Booking.status == "confirmed")
        ).all()
        # Exactly 2 confirmed (one loser at old time, one winner at 09:30)
        assert len(confirmed) == 2
        starts = {b.start_time for b in confirmed}
        assert datetime(2026, 8, 31, 9, 30, tzinfo=UTC) in starts


def test_booking_filters_from_to(client: TestClient) -> None:
    token = _register_host(client, "alice10@example.com", "alice10")
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        r1 = client.post(
            "/alice10/30min/bookings",
            json={
                "invitee_name": "A",
                "invitee_email": "a@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
        assert client.post(
            "/alice10/30min/bookings",
            json={
                "invitee_name": "B",
                "invitee_email": "b@example.com",
                "slot_start": "2026-08-31T10:00:00Z",
            },
        ).status_code == 201
    id1 = r1.json()["id"]
    headers = _auth_headers(token)
    # Filter from after first booking
    resp = client.get("/bookings?from=2026-08-31T09:30:00Z", headers=headers)
    assert resp.status_code == 200
    ids = {b["id"] for b in resp.json()}
    assert id1 not in ids
    # Filter to before second booking's end
    resp = client.get("/bookings?to=2026-08-31T09:30:00Z", headers=headers)
    ids = {b["id"] for b in resp.json()}
    assert id1 in ids
