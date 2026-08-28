"""TDD coverage for Issue #5 public booking creation.

Confirmed seams: POST /{username}/{event_slug}/bookings and PostgreSQL's
confirmed-booking overlap constraint under concurrent transactions.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from hashlib import sha256
from threading import Barrier
from time import sleep
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from meet_scheduler.bookings.models import Booking
from meet_scheduler.hosts.models import Host
from meet_scheduler.meeting_types.models import MeetingType


@pytest.mark.parametrize(
    "payload",
    [
        {"invitee_email": "bob@example.com", "slot_start": "2026-08-31T09:00:00Z"},
        {"invitee_name": "Bob", "slot_start": "2026-08-31T09:00:00Z"},
        {
            "invitee_name": "Bob",
            "invitee_email": "not-an-email",
            "slot_start": "2026-08-31T09:00:00Z",
        },
        {
            "invitee_name": "Bob",
            "invitee_email": "bob@example.com",
            "slot_start": "2026-08-31T09:00:00",
        },
        {
            "invitee_name": "Bob",
            "invitee_email": "bob@example.com",
            "slot_start": "2026-08-31T09:00:00Z",
            "notes": "x" * 2001,
        },
        {
            "invitee_name": "Bob",
            "invitee_email": "bob@example.com",
            "slot_start": "2026-08-31T09:00:00Z",
            "slot_end": "2026-08-31T18:00:00Z",
        },
    ],
)
def test_booking_validates_the_public_request_contract(
    client: TestClient, payload: dict[str, object]
) -> None:
    _setup_bookable_host(client)

    response = client.post("/alice/30min/bookings", json=payload)

    assert response.status_code == 422


def _setup_bookable_host(client: TestClient) -> None:
    password = "correct horse battery staple"
    assert client.post(
        "/auth/register",
        json={"email": "host@example.com", "password": password},
    ).status_code == 201
    login = client.post(
        "/auth/login", json={"email": "host@example.com", "password": password}
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.put(
        "/me",
        headers=headers,
        json={"username": "alice", "display_name": "Alice", "timezone": "UTC"},
    ).status_code == 200
    assert client.post(
        "/meeting-types",
        headers=headers,
        json={
            "title": "Thirty minutes",
            "event_slug": "30min",
            "duration": 30,
            "active": True,
        },
    ).status_code == 201
    assert client.put(
        "/availability",
        headers=headers,
        json={"windows": [{"weekday": 0, "start": "09:00", "end": "10:00"}]},
    ).status_code == 200


def test_invitee_books_an_exact_generated_slot(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _setup_bookable_host(client)
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)

    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        response = client.post(
            "/alice/30min/bookings",
            json={
                "invitee_name": "Bob Invitee",
                "invitee_email": "bob@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
                "notes": "Discuss the roadmap",
            },
        )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["slot_start"] == "2026-08-31T09:00:00Z"
    assert body["slot_end"] == "2026-08-31T09:30:00Z"
    assert body["invitee_name"] == "Bob Invitee"
    assert body["invitee_email"] == "bob@example.com"
    assert body["notes"] == "Discuss the roadmap"
    assert len(body["management_token"]) >= 43

    with session_factory() as session:
        booking = session.scalar(select(Booking))
        assert booking is not None
        assert booking.end_time == datetime(2026, 8, 31, 9, 30, tzinfo=UTC)
        assert booking.management_token_hash == sha256(
            body["management_token"].encode()
        ).hexdigest()
        assert booking.management_token_hash != body["management_token"]


def test_booking_rejects_a_slot_that_is_not_currently_generated(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _setup_bookable_host(client)
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)

    with patch("meet_scheduler.slots.service.get_now", return_value=request_time):
        response = client.post(
            "/alice/30min/bookings",
            json={
                "invitee_name": "Bob Invitee",
                "invitee_email": "bob@example.com",
                "slot_start": "2026-08-31T09:15:00Z",
            },
        )

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "slot_no_longer_available",
        "message": "The selected slot is no longer available.",
    }
    with session_factory() as session:
        assert session.scalar(select(Booking)) is None


def test_concurrent_attempts_create_exactly_one_confirmed_booking(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _setup_bookable_host(client)
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)

    def book(index: int) -> tuple[int, dict]:
        response = client.post(
            "/alice/30min/bookings",
            json={
                "invitee_name": f"Invitee {index}",
                "invitee_email": f"invitee{index}@example.com",
                "slot_start": "2026-08-31T09:00:00Z",
            },
        )
        return response.status_code, response.json()

    with (
        patch("meet_scheduler.slots.service.get_now", return_value=request_time),
        ThreadPoolExecutor(max_workers=8) as executor,
    ):
        results = list(executor.map(book, range(8)))

    statuses = [result[0] for result in results]
    assert statuses.count(201) == 1, results
    assert statuses.count(409) == 7, results
    for response_status, body in results:
        if response_status == 409:
            assert body["detail"]["code"] in {
                "slot_no_longer_available",
                "booking_conflict",
            }
            assert "invitee" not in str(body).lower()

    with session_factory() as session:
        bookings = session.scalars(
            select(Booking).where(Booking.status == "confirmed")
        ).all()
        assert len(bookings) == 1


def test_postgres_prevents_concurrent_overlapping_confirmed_intervals(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _setup_bookable_host(client)
    with session_factory() as session:
        host_id = session.scalar(select(Host.id).where(Host.username == "alice"))
        meeting_type_id = session.scalar(select(MeetingType.id))
    assert host_id is not None
    assert meeting_type_id is not None

    ready_to_commit = Barrier(8)
    slot_start = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    slot_end = datetime(2026, 8, 31, 9, 30, tzinfo=UTC)

    def insert_booking(index: int) -> bool:
        with session_factory() as session:
            session.add(
                Booking(
                    host_id=host_id,
                    meeting_type_id=meeting_type_id,
                    invitee_name=f"Invitee {index}",
                    invitee_email=f"invitee{index}@example.com",
                    start_time=slot_start,
                    end_time=slot_end,
                    status="confirmed",
                    management_token_hash=sha256(str(index).encode()).hexdigest(),
                    created_at=slot_start,
                    updated_at=slot_start,
                )
            )
            ready_to_commit.wait()
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return False
            return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        inserted = list(executor.map(insert_booking, range(8)))

    assert inserted.count(True) == 1
    assert inserted.count(False) == 7


def test_database_overlap_is_mapped_to_private_conflict_response(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    _setup_bookable_host(client)
    request_time = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)
    slot_start = datetime(2026, 8, 31, 9, 0, tzinfo=UTC)
    slot_end = datetime(2026, 8, 31, 9, 30, tzinfo=UTC)

    with session_factory() as winner_session:
        host_id = winner_session.scalar(
            select(Host.id).where(Host.username == "alice")
        )
        meeting_type_id = winner_session.scalar(select(MeetingType.id))
        assert host_id is not None
        assert meeting_type_id is not None
        winner_session.add(
            Booking(
                host_id=host_id,
                meeting_type_id=meeting_type_id,
                invitee_name="Race winner",
                invitee_email="winner@example.com",
                start_time=slot_start,
                end_time=slot_end,
                status="confirmed",
                management_token_hash=sha256(b"winner").hexdigest(),
                created_at=request_time,
                updated_at=request_time,
            )
        )
        winner_session.flush()

        with (
            patch("meet_scheduler.slots.service.get_now", return_value=request_time),
            ThreadPoolExecutor(max_workers=1) as executor,
        ):
            future = executor.submit(
                client.post,
                "/alice/30min/bookings",
                json={
                    "invitee_name": "Race loser",
                    "invitee_email": "loser@example.com",
                    "slot_start": "2026-08-31T09:00:00Z",
                },
            )
            sleep(0.2)
            winner_session.commit()
            response = future.result()

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "code": "booking_conflict",
            "message": "The selected slot is no longer available.",
        }
    }
    assert "winner" not in response.text.lower()
