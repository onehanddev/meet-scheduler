# ruff: noqa: E501
"""TDD tracer bullet for Issue #4 — public meeting & slots.

Seams under test: GET /{username}/{event_slug} and GET /{username}/{event_slug}/slots
(public HTTP API)
"""
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient


def _register_and_login(client: TestClient, email: str = "host@example.com") -> str:
    client.post("/auth/register", json={"email": email, "password": "correct horse battery staple"})
    resp = client.post("/auth/login", json={"email": email, "password": "correct horse battery staple"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _setup_host(client: TestClient, email: str, username: str, tz: str = "UTC") -> str:
    tok = _register_and_login(client, email=email)
    r = client.put("/me", headers=_auth(tok), json={"username": username, "display_name": "Test Host", "timezone": tz})
    assert r.status_code == 200, r.text
    return tok


def _create_mt(client: TestClient, token: str, duration: int = 30, active: bool = True, title: str = "30 Minute Meeting", slug: str = "30min") -> dict:
    resp = client.post("/meeting-types", headers=_auth(token), json={"title": title, "event_slug": slug, "duration": duration, "active": active})
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_public_meeting_returns_only_public_fields(client: TestClient) -> None:
    tok = _setup_host(client, "h1@example.com", "alice")
    _create_mt(client, tok)
    resp = client.get("/alice/30min")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # must contain required public fields
    assert body["username"] == "alice"
    assert body["display_name"] == "Test Host"
    assert body["timezone"] == "UTC"
    assert body["title"] == "30 Minute Meeting"
    assert body["duration"] == 30
    # privacy: must NOT expose email/hash/invitee data
    assert "email" not in body
    assert "password_hash" not in body
    assert "password" not in str(body).lower()
    # invitee data never exposed via public meeting
    assert "invitee" not in str(body).lower()


def test_slots_requires_bounded_from_to_and_timezone(client: TestClient) -> None:
    tok = _setup_host(client, "h2@example.com", "bob")
    _create_mt(client, tok, slug="30min")
    # missing params -> 422
    r = client.get("/bob/30min/slots")
    assert r.status_code == 422, r.text
    # missing timezone
    r2 = client.get("/bob/30min/slots?from=2026-09-01&to=2026-09-02")
    assert r2.status_code == 422, r2.text
    # invalid timezone -> 422
    r3 = client.get("/bob/30min/slots?from=2026-09-01&to=2026-09-02&timezone=Invalid/Zone")
    assert r3.status_code == 422, r3.text
    # invalid range from > to -> 422
    r4 = client.get("/bob/30min/slots?from=2026-09-10&to=2026-09-01&timezone=UTC")
    assert r4.status_code == 422, r4.text


def test_slots_404_on_unknown_or_inactive(client: TestClient) -> None:
    tok = _setup_host(client, "h3@example.com", "carol")
    _create_mt(client, tok, slug="30min", active=True)
    # unknown user
    r = client.get("/unknown/30min/slots?from=2026-09-01&to=2026-09-02&timezone=UTC")
    assert r.status_code == 404, r.text
    # unknown slug
    r2 = client.get("/carol/unknown/slots?from=2026-09-01&to=2026-09-02&timezone=UTC")
    assert r2.status_code == 404, r2.text
    # deactivate -> 404
    mt = client.get("/meeting-types", headers=_auth(tok)).json()[0]
    upd = client.patch(f"/meeting-types/{mt['id']}", headers=_auth(tok), json={"active": False})
    assert upd.status_code == 200
    r3 = client.get("/carol/30min/slots?from=2026-09-01&to=2026-09-02&timezone=UTC")
    assert r3.status_code == 404, r3.text


def test_slots_expands_weekly_windows_duration_aligned(client: TestClient) -> None:
    """Candidate slots begin at window start and advance by duration; trailing partial excluded."""
    tok = _setup_host(client, "h4@example.com", "dave", tz="UTC")
    _create_mt(client, tok, duration=30, slug="30min")
    # window Monday 09:00-10:15 -> slots 09:00-09:30, 09:30-10:00; 10:00-10:30 would exceed 10:15 excluded
    # Use known Monday date: 2026-08-31 is Monday
    client.put("/availability", headers=_auth(tok), json={"windows": [{"weekday": 0, "start": "09:00", "end": "10:15"}]})
    # need to be outside notice/horizon; freeze now to far earlier
    fake_now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now):
        r = client.get("/dave/30min/slots?from=2026-08-31&to=2026-08-31&timezone=UTC")
        assert r.status_code == 200, r.text
        slots = r.json()["slots"]
        assert len(slots) == 2, slots
        starts = [s["start"] for s in slots]
        # slots should start at 09:00 and 09:30 UTC
        assert any("09:00" in s for s in starts)
        assert any("09:30" in s for s in starts)
        assert not any("10:00" in s for s in starts)  # trailing partial excluded


def test_slots_notice_boundary_60_min(client: TestClient) -> None:
    tok = _setup_host(client, "h5@example.com", "eve", tz="UTC")
    _create_mt(client, tok, duration=30, slug="30min")
    # window every weekday 09:00-12:00
    client.put("/availability", headers=_auth(tok), json={"windows": [{"weekday": 0, "start": "09:00", "end": "12:00"}]})
    # Monday 2026-08-31 09:00 host window; now is 2026-08-31 08:00 UTC, notice 60min -> slot at 09:00 allowed (exactly 60), 08:59 rejected
    # So we test both: now 08:01 -> slot at 09:00 is 59min away -> rejected; now 08:00 -> allowed
    fake_now_allowed = datetime(2026, 8, 31, 8, 0, 0, tzinfo=UTC)
    fake_now_rejected = datetime(2026, 8, 31, 8, 0, 1, tzinfo=UTC)  # 59:59 away
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now_allowed):
        r = client.get("/eve/30min/slots?from=2026-08-31&to=2026-08-31&timezone=UTC")
        assert r.status_code == 200
        slots = r.json()["slots"]
        assert any("09:00" in s["start"] for s in slots), slots
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now_rejected):
        r2 = client.get("/eve/30min/slots?from=2026-08-31&to=2026-08-31&timezone=UTC")
        assert r2.status_code == 200
        slots2 = r2.json()["slots"]
        # 09:00 slot is 59:59 away -> should be excluded
        assert not any("09:00" in s["start"] for s in slots2), slots2


def test_slots_horizon_60_days(client: TestClient) -> None:
    tok = _setup_host(client, "h6@example.com", "frank", tz="UTC")
    _create_mt(client, tok, duration=30, slug="30min")
    client.put("/availability", headers=_auth(tok), json={"windows": [{"weekday": 0, "start": "09:00", "end": "10:00"}]})
    now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    # Horizon default 60 days -> allowed up to 2026-03-02 10:00
    # Find Monday after horizon: 2026-03-09 is Monday beyond horizon
    with patch("meet_scheduler.slots.service.get_now", return_value=now):
        r = client.get("/frank/30min/slots?from=2026-03-09&to=2026-03-09&timezone=UTC")
        assert r.status_code == 200
        assert r.json()["slots"] == [], r.json()
        # Within horizon should have slots
        # 2026-02-02 is Monday within horizon
        r2 = client.get("/frank/30min/slots?from=2026-02-02&to=2026-02-02&timezone=UTC")
        assert r2.status_code == 200
        assert len(r2.json()["slots"]) > 0, r2.json()


def test_slots_dst_spring_forward_gap_no_slot(client: TestClient) -> None:
    # Host America/New_York: DST spring forward 2026-03-08 gap 02:00-03:00
    tok = _setup_host(client, "h7@example.com", "grace", tz="America/New_York")
    _create_mt(client, tok, duration=30, slug="30min")
    # Window Sunday 01:00-04:00 includes gap
    client.put("/availability", headers=_auth(tok), json={"windows": [{"weekday": 6, "start": "01:00", "end": "04:00"}]})
    # 2026-03-08 is Sunday
    fake_now = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now):
        r = client.get("/grace/30min/slots?from=2026-03-08&to=2026-03-08&timezone=UTC")
        assert r.status_code == 200, r.text
        slots = r.json()["slots"]
        # Expect slots at 01:00, 01:30, 03:00, 03:30 but NOT 02:00/02:30 (gap)
        starts = [s["start"] for s in slots]
        # Ensure no slot corresponds to host 02:00/02:30 local (which would be 07:00/07:30 UTC)
        # Convert UTC starts to host local for check
        # Simplest: ensure total slots excludes gap -> should be 4 slots minus gap? Window 3h = 6*30min but 2 nonexistent => 4 slots
        assert len(slots) == 4, f"expected 4 slots but got {len(slots)} {slots}"
        # No duplicate UTC instants
        assert len(set(starts)) == len(starts)


def test_slots_fall_back_no_duplicate(client: TestClient) -> None:
    # Fall back 2026-11-01 America/New_York: 01:00-02:00 occurs twice
    tok = _setup_host(client, "h8@example.com", "heidi", tz="America/New_York")
    _create_mt(client, tok, duration=30, slug="30min")
    client.put("/availability", headers=_auth(tok), json={"windows": [{"weekday": 6, "start": "00:30", "end": "03:00"}]})
    # 2026-11-01 is Sunday
    fake_now = datetime(2026, 10, 25, 10, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now):
        r = client.get("/heidi/30min/slots?from=2026-11-01&to=2026-11-01&timezone=UTC")
        assert r.status_code == 200, r.text
        slots = r.json()["slots"]
        starts = [s["start"] for s in slots]
        # Ensure no duplicate UTC instants
        assert len(starts) == len(set(starts)), f"duplicate UTC {starts}"
        # With window 00:30-03:00 duration 30 -> candidates 00:30,01:00,01:30,02:00,02:30 -> 5 slots; DST fall should not duplicate or add extra
        # Ensure we get at most 5
        assert len(slots) <= 5, slots

def test_slots_invitee_timezone_conversion(client: TestClient) -> None:
    tok = _setup_host(client, "h9@example.com", "ivan", tz="UTC")
    _create_mt(client, tok, duration=30, slug="30min")
    # Monday 09:00-10:00 UTC
    client.put("/availability", headers=_auth(tok), json={"windows": [{"weekday": 0, "start": "09:00", "end": "10:00"}]})
    fake_now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now):
        # Request in Europe/Berlin (UTC+2 summer)
        r = client.get("/ivan/30min/slots?from=2026-08-31&to=2026-08-31&timezone=Europe/Berlin")
        assert r.status_code == 200, r.text
        slots = r.json()["slots"]
        assert len(slots) > 0
        # Slot start in Berlin should be 11:00+02:00 (since host 09:00 UTC = 11:00 Berlin)
        assert any("11:00" in s["start"] for s in slots), slots
        # Host UTC 09:30 -> Berlin 11:30
        assert any("11:30" in s["start"] for s in slots), slots


def test_slots_empty_schedule_no_slots(client: TestClient) -> None:
    tok = _setup_host(client, "h10@example.com", "judy", tz="UTC")
    _create_mt(client, tok, slug="30min")
    client.put("/availability", headers=_auth(tok), json={"windows": []})
    fake_now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now):
        r = client.get("/judy/30min/slots?from=2026-08-31&to=2026-09-01&timezone=UTC")
        assert r.status_code == 200
        assert r.json()["slots"] == []


def test_slots_excludes_confirmed_overlapping_bookings(client: TestClient, session_factory) -> None:
    tok = _setup_host(client, "h11@example.com", "karl", tz="UTC")
    mt = _create_mt(client, tok, duration=30, slug="30min")
    client.put("/availability", headers=_auth(tok), json={"windows": [{"weekday": 0, "start": "09:00", "end": "11:00"}]})
    # need host id and meeting type id
    from uuid import UUID

    from meet_scheduler.bookings.models import Booking

    me = client.get("/me", headers=_auth(tok)).json()
    host_id = UUID(me["id"])
    mt_id = UUID(mt["id"])
    # Monday 2026-08-31 09:00 UTC slot should be booked
    booking_start = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    booking_end = datetime(2026, 8, 31, 9, 30, tzinfo=UTC)
    now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    # insert confirmed booking directly
    factory = session_factory
    with factory() as s:
        s.add(
            Booking(
                host_id=host_id,
                meeting_type_id=mt_id,
                invitee_name="Bob",
                invitee_email="bob@example.com",
                start_time=booking_start,
                end_time=booking_end,
                status="confirmed",
                created_at=now,
                updated_at=now,
            )
        )
        s.commit()
    fake_now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now):
        r = client.get("/karl/30min/slots?from=2026-08-31&to=2026-08-31&timezone=UTC")
        assert r.status_code == 200, r.text
        slots = r.json()["slots"]
        # 09:00 should be excluded
        assert not any("09:00" in s["start"] for s in slots), slots
        # 09:30 should still be available
        assert any("09:30" in s["start"] for s in slots), slots
        # 10:00 etc.
        assert len(slots) == 3, slots  # 09:30,10:00,10:30 (4 total minus 1 booked)


def test_slots_cancelled_booking_does_not_block(client: TestClient, session_factory) -> None:
    tok = _setup_host(client, "h12@example.com", "lisa", tz="UTC")
    mt = _create_mt(client, tok, duration=30, slug="30min")
    client.put("/availability", headers=_auth(tok), json={"windows": [{"weekday": 0, "start": "09:00", "end": "10:00"}]})
    from uuid import UUID

    from meet_scheduler.bookings.models import Booking

    me = client.get("/me", headers=_auth(tok)).json()
    host_id = UUID(me["id"])
    mt_id = UUID(mt["id"])
    now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    booking_start = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    booking_end = datetime(2026, 8, 31, 9, 30, tzinfo=UTC)
    with session_factory() as s:
        s.add(
            Booking(
                host_id=host_id,
                meeting_type_id=mt_id,
                invitee_name="Bob",
                invitee_email="bob@example.com",
                start_time=booking_start,
                end_time=booking_end,
                status="cancelled",
                created_at=now,
                updated_at=now,
            )
        )
        s.commit()
    fake_now = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    with patch("meet_scheduler.slots.service.get_now", return_value=fake_now):
        r = client.get("/lisa/30min/slots?from=2026-08-31&to=2026-08-31&timezone=UTC")
        assert r.status_code == 200
        slots = r.json()["slots"]
        # cancelled should not block
        assert any("09:00" in s["start"] for s in slots), slots
        assert len(slots) == 2, slots
