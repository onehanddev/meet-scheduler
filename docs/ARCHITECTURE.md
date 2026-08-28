# Architecture

## Overview

Meet Scheduler is an API-first FastAPI + PostgreSQL backend. Domain logic is split into deep modules behind narrow seams; the public booking path is transactional and time-correct (DST-aware, notice/horizon enforced, overlap blocked by Postgres).

```
Client (invitee/host)
  │
  ├─ POST /auth/register, /auth/login, /auth/refresh, /auth/logout, GET /auth/me, GET|PUT /me
  ├─ POST|GET|PUT|PATCH /meeting-types[/{id}]
  ├─ GET|PUT /availability
  ├─ GET|POST /bookings[/{id}/cancel|reschedule]   (host + token-protected)
  ├─ GET /{username}/{event_slug}                   (public)
  ├─ GET /{username}/{event_slug}/slots             (public)
  └─ POST /{username}/{event_slug}/bookings         (public)
       │
       ▼
   FastAPI routers (src/meet_scheduler/*/router.py)
       │
       ├─ dependencies.py:get_current_host  (shared auth seam → Security)
       ├─ availability/provider.py:WeeklyAvailabilityProvider  (slot input boundary)
       └─ slots/service.py:generate_slots / generate_host_slots (pure engine)
       │
       ▼
   SQLAlchemy ORM → PostgreSQL (Alembic migrations)
```

## Domain Model

| Entity | Table | Notes |
|---|---|---|
| Host | `hosts` | `id` PK, `email` unique, `password_hash` (Argon2id), `username` (partial unique `lower(username)`), `display_name`, `timezone` (IANA). |
| RefreshToken | `refresh_tokens` | `jti` PK, `host_id` FK, `revoked`, `expires_at`, `created_at`. One row per issued refresh JWT. |
| MeetingType | `meeting_types` | One per `host_id` (unique), `(host_id, lower(event_slug))` unique, `title`, `duration`, `active`, `minimum_notice` (60), `horizon_days` (60). |
| AvailabilityWindow | `availability_windows` | `host_id` FK, `weekday` 0–6, `start_time`/`end_time` (host-local `TIME`). No DB-level overlap guard — validated in app, replaced atomically. |
| Booking | `bookings` | `host_id`, `meeting_type_id`, `invitee_name/email`, `notes`, `start_time`/`end_time` (`timestamptz` UTC), `status` (`confirmed`/`cancelled`), `management_token_hash` (SHA-256), `predecessor_id` (self-FK for reschedule trace), `created_at`/`updated_at`. `EXCLUDE USING gist` on `host_id + tstzrange` where `status='confirmed'`. |

### Public Identity

`username` + `event_slug` form the public URL `/{username}/{event_slug}`. Both are lowercased, URL-safe `^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$`, reserved names blocked. Changing `username` changes the URL; no redirect history.

## Modules (deep modules + seams)

| Module | Entry points | External seam |
|---|---|---|
| `hosts/auth` | `/auth/*` | `password_hasher` + `jwt.encode/decode` + `RefreshToken` rows |
| `hosts/profile` | `/me` | `dependencies.get_current_host` |
| `meeting_types` | `/meeting-types*` | same |
| `availability` | `/availability` | `validate_windows_no_overlap` + atomic `DELETE+INSERT` under `FOR UPDATE` host lock |
| `slots/service` | (no HTTP) | **Pure** `generate_slots(windows, host_tz, duration, from/to, invitee_tz, now, notice, horizon, bookings)` + provider `get_windows` |
| `bookings` | `/bookings*` | `create_booking`, `cancel_booking`, `reschedule_booking` (transactional, token-hashed) |
| `public` | `/{u}/{s}`, `/{u}/{s}/slots`, `/{u}/{s}/bookings` | `resolve_host_and_meeting` + `generate_host_slots` |
| `dependencies` | (shared) | Single `get_current_host(Authorization: Bearer)` factory |
| `security` | (shared) | `decode_token`, `get_host_id_from_access_token` |
| `database` | (shared) | `create_session_factory`, `session_scope` |

### Availability Provider Boundary

`availability/provider.py:WeeklyAvailabilityProvider.get_windows(host_id)` is the **only** place that reads windows for slot generation. Present provider returns weekly windows verbatim; a future provider that merges weekly windows with date-specific overrides / holidays can replace it without touching `slots/service.py` or `bookings/service.py`.

## Slot Generation

`slots/service.py:generate_slots` is pure and timezone-correct:

1. Group windows by weekday.
2. Iterate `from_date … to_date`; for each window step by `duration` from `start`, emitting candidates whose `[start, start+duration)` fits inside the window.
3. Convert host wall time → UTC via `zoneinfo`, detecting DST gaps (nonexistent `02:30` on spring-forward → `None` → skip). Day arithmetic uses host-local dates.
4. Filter candidates: `start < now+notice` (exactly equal is allowed), `start > now+horizon`, overlaps any confirmed booking (`slot_start < booking_end && booking_start < slot_end`), duplicate UTC (fall-back) deduped.
5. Re-localize surviving candidates to invitee timezone. Sort by `start_utc`.

`generate_host_slots` is the DB-aware wrapper that loads `WeeklyAvailabilityProvider` windows and `fetch_confirmed_bookings` then delegates to `generate_slots`.

## Booking Correctness

All booking writes run inside a single transaction with advisory revalidation:

- `create_booking` locks host `FOR KEY SHARE` (so concurrent bookings don’t block each other) and meeting type `FOR SHARE`, verifies `username`/`event_slug` case-insensitive, re-derives `valid_starts` via `generate_host_slots` for that UTC date, then inserts `Booking(status='confirmed')`. `IntegrityError` on `ex_bookings_host_confirmed_overlap` → `409 booking_conflict`.
- `cancel_booking` locks booking `FOR UPDATE`, checks token hash, idempotent on already-cancelled.
- `reschedule_booking` locks booking `FOR UPDATE`, verifies token, rejects `new_slot_start == old`, locks host/type, recomputes `filtered_confirmed` (excluding self), validates via `generate_slots` with filtered set, then atomically inserts replacement (copies token hash, `predecessor_id = old.id`) and cancels old in the same commit. `IntegrityError` on exclude → `409 booking_conflict`.

Lock modes are intentional: configuration writers (`PUT /me`, `PUT /meeting-types`, `PUT /availability`) use `FOR UPDATE` on host so they serialize; booking path uses `FOR KEY SHARE` so bookings serialize only against config changes, not each other — letting the EXCLUDE constraint be the concurrency arbiter.

## Cross-Cutting Concerns

- **Config**: `config.py:Settings` (`pydantic-settings`, `env_file=.env`). `DATABASE_URL`, `TOKEN_SECRET` required.
- **Error envelope**: `main.py` has global handlers for `BookingError` and `HTTPException`/`RequestValidationError`, all returning `{code, message, details}`.
- **Privacy**: Public routes (`public/router.py`, `public/service.py`) never return email, password hash, invitee data, or `host_id`. Conflict errors scrub invitee identity.
- **Clock**: `slots/service.py:get_now()` is the single request-scoped clock; tests patch it with `unittest.mock.patch`.

## Migrations

`migrations/versions/` — 9 Alembic revisions (`20260828_01` … `20260828_09`). Linear chain, no branches. Key revision is `20260828_07` which does `CREATE EXTENSION IF NOT EXISTS btree_gist` and `ALTER TABLE bookings ADD CONSTRAINT … EXCLUDE USING gist`. To add a migration: `alembic revision -m "..."` and fill `upgrade`/`downgrade`, then `alembic upgrade head`.

## Request Flow (booking example)

```
POST /alice/30min/bookings {slot_start:2026-09-01T09:00:00Z}
  → public/router.create_booking_public
    → public/service.resolve_host_and_meeting (host+mt lookup, active check)
    → bookings/service.create_booking
        lock_host(FOR KEY SHARE), lock meeting_type(FOR SHARE)
        re-check username/slug/active, compute valid_starts via slots
        insert Booking + commit
          ↳ on EXCLUDE violation → BookingError(booking_conflict,409)
    → 201 + management_token (raw token returned once, digest persisted)
```

## Decisions & Constraints

- PostgreSQL is required (not SQLite) because overlap semantics and the `tstzrange` + `EXCLUDE` constraint are core product guarantees.
- App-level time parsing/validation (`availability/service.py`, `meeting_types/service.py`) defends the boundary before DB writes.
- No ORM-level composite constraints for availability overlap — app validation (`validate_windows_no_overlap`) is the invariant; windows are replaced atomically so partial updates never leak.

See `PRD.md` § Implementation Decisions and `docs/KNOWN_ISSUES.md` for what’s intentionally out of scope.
