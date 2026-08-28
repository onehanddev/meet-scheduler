# Meet Scheduler

Minimal one-on-one meeting scheduler backend — inspired by Calendly and Cal.com — with a focus on correctness: timezone-aware slots, notice and horizon rules, DST handling, and transactional overlap protection under concurrency.

> **Status:** All core product features from `PRD.md` are implemented and covered by 96 integration tests. See [Known Issues](#known-issues--gaps) for remaining gaps.

---

## Table of Contents

- [What it does](#what-it-does)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Quickstart](#quickstart) — two paths: local Postgres or Docker
- [Environment](#environment)
- [Database & Migrations](#database--migrations)
- [Running the API](#running-the-api)
- [API Overview](#api-overview)
- [Examples (curl)](#examples-curl)
- [Slot Rules in 30 Seconds](#slot-rules-in-30-seconds)
- [Testing](#testing)
- [Lint & Type Checks](#lint--type-checks)
- [Project Layout](#project-layout)
- [Docs Index](#docs-index)
- [Known Issues & Gaps](#known-issues--gaps)
- [Troubleshooting](#troubleshooting)

---

## What It Does

- A **host** registers with email + password, signs in to get JWTs, picks a public `username`, sets an IANA timezone and display name, creates **one** meeting type (15/30/45/60 min), and publishes **recurring weekly availability** windows per weekday.
- The public booking surface is `/{username}/{event-slug}`. An **invitee** (no account) fetches meeting info and **slots** localized to their timezone, then posts a booking with name + email + selected `slot_start`. The invitee receives a one-time **management token** to `cancel` or `reschedule` without ever creating an account.
- Every slot and booking is revalidated inside a Postgres transaction and collisions are blocked by a **`btree_gist` EXCLUDE constraint** — so 8 concurrent `POST /{u}/{s}/bookings` for the same instant yield exactly one `201` and seven `409`s.

Out-of-scope by design (see `PRD.md` § Out of Scope): OAuth, email verification, calendar sync, notifications, conferencing links, organizations, buffers, multiple meeting types per host, frontend.

---

## Features

### Authentication
- `POST /auth/register` — email (normalized, case-insensitive unique) + password 8–128 chars. Password stored as **Argon2id** hash; never returned, never logged. Returns safe profile.
- `POST /auth/login` — constant-time “Invalid email or password” for unknown email or bad password. Issues **JWT access (15 min)** and **JWT refresh (30 days)**, each with `sub`, `type`, `iat`, `exp`, `jti`. `jti` is persisted as a revocable `refresh_tokens` row.
- `POST /auth/refresh` — rotates refresh token (used token is revoked; replay is rejected).
- `POST /auth/logout` — revokes the submitted refresh token.
- `GET /auth/me` / `GET /me` — current host profile.
- Refresh tokens are revoked on use; access tokens are short-lived and not revoked server-side.

### Host Profile
- `GET /me` / `PUT /me` — read/update `username`, `display_name`, `timezone`.
- `username`: 3–30 chars, URL-safe `^[a-z0-9]([a-z0-9_-]*[a-z0-9])?$`, lowercased, case-insensitive unique, reserved names (`admin`, `api`, `auth`, `docs`, `health`, `healthz`, `login`, `logout`, `me`, `openapi`, `redoc`, `refresh`, `register`, `static`) rejected.
- `display_name`: 1–100 chars, trimmed.
- `timezone`: any valid IANA zone (`ZoneInfo` validated). Changing username changes the public URL; no redirect history.

### Meeting Type (one-per-host singleton)
- `POST /meeting-types` — create. `GET /meeting-types` / `GET /meeting-types/{id}` — read. `PUT|PATCH /meeting-types` and `PUT|PATCH /meeting-types/{id}` — update.
- Fields: `title` (1–200 chars), `event_slug` (URL-safe, reserved-checked), `duration` ∈ {15,30,45,60}, `active` bool, `minimum_notice` (minutes, 0–10080, default 60), `horizon_days` (1–365, default 60). Aliases `minimum_notice_minutes` and `horizon` accepted for compat.
- Second `POST` for same host → `409`. Deactivating (`active: false`) makes `GET /{u}/{s}` and `GET /{u}/{s}/slots` return `404` with `meeting_type_inactive` and rejects `POST …/bookings`.

### Weekly Availability
- `GET /availability` / `PUT /availability` — list and **atomically replace** the full weekly schedule in one transaction (host row is `FOR UPDATE` locked, old windows deleted, new inserted, then committed).
- Body: `{ windows: [{ weekday: 0–6 (Mon=0), start: "HH:MM", end: "HH:MM" }, …] }`. Empty `windows: []` = fully closed. Multiple windows per weekday allowed; **overlapping windows on same weekday → 422**; adjacent windows allowed. `start < end` enforced; overnight windows not supported (split across weekdays). Times are stored as host-local wall-clock values so they track DST.

### Public Surface (no auth)
- `GET /{username}/{event-slug}` → `{ username, display_name, timezone, title, duration, event_slug }`. Never exposes email, password hash, or invitee data.
- `GET /{username}/{event-slug}/slots?from=YYYY-MM-DD&to=YYYY-MM-DD&timezone=IANA` → `{ slots: [{ start, end, start_utc, end_utc }], timezone }`. Validates invitee timezone, bounded `from ≤ to`, inactive/unknown → `404` with `host_not_found` / `meeting_type_not_found` / `meeting_type_inactive`.
- `POST /{username}/{event-slug}/bookings` with `{ invitee_name, invitee_email, slot_start: ISO8601-with-tz, notes? }` → `201 { id, status:"confirmed", slot_start, slot_end, management_token }`. `slot_end` is server-derived. `notes` ≤ 2000 chars. Extra fields rejected (`extra="forbid"`). Conflict/privacy: `409` bodies never leak invitee emails or host ids.

### Slots Engine
- Pure function `slots/service.py:generate_slots` consumed via `availability/provider.py:WeeklyAvailabilityProvider` boundary (future override provider can be swapped without changing booking APIs).
- Candidates step by `duration` from each window start; trailing partial intervals excluded. Each candidate converted host-local → UTC with DST gap detection (`None` for nonexistent times), then re-localized to invitee timezone.
- Filters: `slot_start < now + minimum_notice` excluded (exactly at cutoff is allowed), `slot_start > now + horizon_days` excluded, overlaps any `confirmed` booking excluded, duplicate UTC instants (DST fall-back) deduped. Results sorted by `start_utc`. Advisory only — revalidated transactionally at booking time.

### Bookings & Lifecycle
- `GET /bookings?status=confirmed|cancelled&from=ISO&to=ISO` and `GET /bookings/{id}` — host-scoped list/detail (ownership enforced).
- `POST /bookings/{id}/cancel` with `{ management_token }` — idempotent; cancelled stays cancelled.
- `POST /bookings/{id}/reschedule` with `{ management_token, new_slot_start }` — atomically creates replacement booking (copies token hash, sets `predecessor_id`), cancels old, revalidates new slot against filtered confirmed set (excludes self). `new_slot_start == old` → `409 reschedule_same_interval`. Uses `FOR UPDATE` on booking, `FOR KEY SHARE` on host (bookings don’t block each other), `FOR SHARE` on meeting type.
- Management tokens are `secrets.token_urlsafe(32)` hashed with SHA-256; only the digest is persisted.
- `bookings` table has `EXCLUDE USING gist (host_id WITH =, tstzrange(start_time,end_time,'[)') WITH &&) WHERE (status='confirmed')` backed by `btree_gist`.

### Errors
- Consistent envelope across all handlers (`main.py`): `{ code, message, details[] }`. Codes include `validation_error`, `unauthenticated`, `unauthorized`, `not_found`, `conflict`, plus booking-domain codes `host_not_found`, `meeting_type_not_found`, `meeting_type_inactive`, `host_timezone_not_set`, `slot_no_longer_available`, `booking_conflict`, `invalid_management_token`, `booking_not_found`, `booking_not_confirmed`, `reschedule_same_interval`, `request_error`.

### Health
- `GET /healthz` → `{ status: "ok" }`.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| API | FastAPI 0.115+ (Starlette 1.x) |
| DB | PostgreSQL 16 (required for `btree_gist` + range EXCLUDE) |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Auth | Argon2id (`argon2-cffi`) + PyJWT (HS256) |
| Validation | Pydantic v2 |
| Tests | pytest + pytest-asyncio + FastAPI TestClient + real Postgres |
| Lint | Ruff |

Supported platforms: macOS, Linux, Windows (WSL2). Windows native works but Docker path is recommended there.

---

## Quickstart

### Prereqs

- Python 3.12 (check `python3 --version`; with pyenv: `pyenv install 3.12 && pyenv local 3.12`)
- PostgreSQL 16 (or Docker — see Option B)
- Node/Yarn only if you want `yarn run lint` (Ruff is also available as `.venv/bin/ruff check`)

### Option A — Local Postgres (Homebrew)

```bash
# 1. Clone & Python env
git clone <repo-url> meet-scheduler && cd meet-scheduler
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Postgres DBs
brew services start postgresql@14   # or @16, adjust to your install
createdb meet_scheduler
createdb meet_scheduler_test        # required — tests refuse any other DB name

# 3. Env & migrations
cp .env.example .env
# Edit .env if needed (DATABASE_URL, TOKEN_SECRET), or keep defaults for local dev
alembic upgrade head

# 4. Run
uvicorn meet_scheduler.main:app --reload
# → http://127.0.0.1:8000  ·  docs at http://127.0.0.1:8000/docs  ·  health at /healthz
```

### Option B — Docker (no local Postgres needed)

```bash
git clone <repo-url> meet-scheduler && cd meet-scheduler
cp .env.example .env
docker compose up -d --build
# DB is at postgres:5432 inside compose; override DATABASE_URL on host if you run the API outside compose:
#   DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/meet_scheduler
alembic upgrade head
uvicorn meet_scheduler.main:app --reload  # or: docker compose logs -f api
```

`docker-compose.yml` ships with the repo (`db` on `5432:5432`, `api` on `8000:8000`, named volume `pgdata`, healthcheck on `pg_isready`). The `btree_gist` extension is created by migration `20260828_07`; no manual superuser step is needed if the DB user is `postgres` (superuser by default in the compose image).

### Make shortcuts

```bash
make install     # venv + pip install -e ".[dev]"
make db-create   # createdb both DBs (no-op if they exist)
make migrate     # alembic upgrade head
make lint        # ruff check .
make lint-fix    # ruff check . --fix
make test        # pytest -q
make api         # uvicorn --reload
make docker-up   # compose up + wait + migrate
make docker-down # compose down
```

---

## Environment

| Var | Required | Default / Example | Notes |
|---|---|---|---|
| `APP_ENV` | no | `development` | Informational only. |
| `DATABASE_URL` | yes | `postgresql+psycopg://postgres:postgres@localhost:5432/meet_scheduler` | API + Alembic. In compose, use `@db:5432`. |
| `TEST_DATABASE_URL` | for tests | `postgresql+psycopg://postgres:postgres@localhost:5432/meet_scheduler_test` | Read only by `tests/conftest.py`. **DB name must be `meet_scheduler_test`** or pytest aborts. |
| `TOKEN_SECRET` | yes | `change-me-in-development` | HS256 secret. Generate a real one for prod: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |

Config is `pydantic-settings` (`config.py:Settings`) reading `.env` via `env_file=.env`. Alembic also reads `DATABASE_URL` at runtime when invoked through the app path; `alembic.ini` carries a fallback URL for offline use.

Never commit `.env`.

---

## Database & Migrations

- Migrations live in `migrations/versions/` (9 revisions, `20260828_01` → `20260828_09`). They are repeatable and safe on a clean DB.
- Apply: `alembic upgrade head`. Revert: `alembic downgrade base`. Inspect: `alembic history`, `alembic current`.

Key DB guarantees:
- `hosts.username` — case-insensitive unique via `lower(username)` partial unique index.
- `meeting_types` — one per `host_id` (unique), `(host_id, lower(event_slug))` unique.
- `bookings` — `EXCLUDE USING gist` on `host_id + tstzrange` requiring `btree_gist` — created in `20260828_07_prevent_overlapping_bookings.py`.

If migrations fail with `btree_gist` / permission errors, ensure the DB user is superuser or `CREATE EXTENSION btree_gist` manually as superuser.

---

## Running the API

```bash
uvicorn meet_scheduler.main:app --reload
# or: make api
```

- OpenAPI docs: `http://127.0.0.1:8000/docs` (Swagger) and `/redoc`
- Health: `GET /healthz`
- Structured error envelope on every 4xx: `{ code, message, details }`

---

## API Overview

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/auth/register` | no | Register host |
| POST | `/auth/login` | no | Login → `{ access_token, refresh_token, token_type, expires_in }` |
| POST | `/auth/refresh` | no (body `refresh_token`) | Rotate refresh token |
| POST | `/auth/logout` | no (body `refresh_token`) | Revoke refresh token |
| GET | `/auth/me` | Bearer | Current host |
| GET | `/me` | Bearer | Current host (alias) |
| PUT | `/me` | Bearer | Update profile (`username`, `display_name`, `timezone`) |
| POST | `/meeting-types` | Bearer | Create one meeting type |
| GET | `/meeting-types` | Bearer | List (0 or 1) |
| GET | `/meeting-types/{id}` | Bearer | Get by id |
| PUT | `/meeting-types/{id}` | Bearer | Update by id |
| PATCH | `/meeting-types/{id}` | Bearer | Patch by id (same as PUT) |
| PUT | `/meeting-types` | Bearer | Update singleton |
| PATCH | `/meeting-types` | Bearer | Patch singleton |
| GET | `/availability` | Bearer | List windows |
| PUT | `/availability` | Bearer | Replace all windows atomically |
| GET | `/bookings` | Bearer | List own bookings (`?status&from&to`) |
| GET | `/bookings/{id}` | Bearer | Get own booking |
| POST | `/bookings/{id}/cancel` | token | Cancel via management token |
| POST | `/bookings/{id}/reschedule` | token | Reschedule via management token |
| GET | `/{username}/{event_slug}` | no | Public meeting info |
| GET | `/{username}/{event_slug}/slots` | no | Public slots (`?from&to&timezone`) |
| POST | `/{username}/{event_slug}/bookings` | no | Create booking → `management_token` |
| GET | `/healthz` | no | Health check |

Full request/response schemas and error codes: see `docs/API.md`.

---

## Examples (curl)

```bash
BASE=http://127.0.0.1:8000

# Register & login
curl -s $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"correct horse battery staple"}'
curl -s $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"correct horse battery staple"}' | jq
TOKEN=$(curl -s $BASE/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"alice@example.com","password":"correct horse battery staple"}' | jq -r .access_token)

# Profile
curl -s $BASE/me -H "Authorization: Bearer $TOKEN" | jq
curl -s -X PUT $BASE/me -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"username":"alice","display_name":"Alice","timezone":"America/New_York"}' | jq

# Meeting type
curl -s -X POST $BASE/meeting-types -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"30 Minute Meeting","event_slug":"30min","duration":30}' | jq

# Availability — Monday 09:00-12:00 and 13:00-17:00, Tuesday 09:00-17:00
curl -s -X PUT $BASE/availability -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"windows":[
    {"weekday":0,"start":"09:00","end":"12:00"},{"weekday":0,"start":"13:00","end":"17:00"},
    {"weekday":1,"start":"09:00","end":"17:00"}
  ]}' | jq

# Public: meeting + slots (invitee asks in their own TZ)
curl -s $BASE/alice/30min | jq
curl -s "$BASE/alice/30min/slots?from=2026-09-01&to=2026-09-07&timezone=Europe/Berlin" | jq

# Public: book
RESP=$(curl -s -X POST $BASE/alice/30min/bookings -H 'Content-Type: application/json' \
  -d '{"invitee_name":"Bob","invitee_email":"bob@example.com","slot_start":"2026-09-01T09:00:00Z"}')
echo $RESP | jq
BOOKING_ID=$(echo $RESP | jq -r .id)
MGMT=$(echo $RESP | jq -r .management_token)

# Manage via token (no auth)
curl -s -X POST $BASE/bookings/$BOOKING_ID/cancel -H 'Content-Type: application/json' \
  -d "{\"management_token\":\"$MGMT\"}" | jq
# Reschedule instead:
# curl -s -X POST $BASE/bookings/$BOOKING_ID/reschedule -H 'Content-Type: application/json' \
#   -d "{\"management_token\":\"$MGMT\",\"new_slot_start\":\"2026-09-01T09:30:00Z\"}" | jq
```

---

## Slot Rules in 30 Seconds

- Wall-clock windows are per-host timezone; slots step by `duration` from each window start; trailing partial excluded.
- Filters: `slot_start < now + minimum_notice` → excluded; `slot_start > now + horizon_days` → excluded; overlaps confirmed booking → excluded; cancelled bookings don’t block.
- DST: nonexistent local times (spring-forward gap) → no slot; ambiguous times (fall-back) → UTC-deduped, no duplicate slots.
- Advisory: every rule is re-checked inside the booking transaction.

---

## Testing

```bash
pytest -q              # requires meet_scheduler_test DB + migrations applied
pytest -v -k test_slots
```

- `tests/conftest.py` creates a `session_factory` that **downgrades to `base` then upgrades to `head` per test session** and tears down afterwards. It refuses to run unless the DB URL database is `meet_scheduler_test`.
- Coverage: 96 tests across `auth`, `profile`, `meeting-type`, `availability`, `public/slots`, `public/bookings`, `bookings/lifecycle`, `health` — including DST, notice boundary (`59:59` rejected / `60:00` allowed), horizon, concurrent booking races (8 threads), `btree_gist` contention, and configuration-wait revalidation.
- To target the test DB explicitly: `TEST_DATABASE_URL=postgresql+psycopg://…/meet_scheduler_test pytest -q`

---

## Lint & Type Checks

```bash
yarn run lint        # ruff check .
yarn run lint:fix    # ruff check . --fix
# or directly:
.venv/bin/ruff check .
.venv/bin/ruff check . --fix
pytest -q            # must stay green before pushing
```

Ruff config: `pyproject.toml` (`line-length=88`, `target-version=py312`, `select=E,F,I,UP,B`). CI should run both lint and pytest.

---

## Project Layout

```
.
├── src/meet_scheduler/
│   ├── main.py              # app factory, error envelope
│   ├── config.py            # pydantic-settings (DATABASE_URL, TOKEN_SECRET)
│   ├── database.py          # engine / session factory
│   ├── security.py          # JWT decode / Bearer parsing
│   ├── dependencies.py      # get_current_host factory (shared auth seam)
│   ├── hosts/               # auth, profile, models
│   ├── meeting_types/       # singleton meeting type CRUD
│   ├── availability/        # windows models + provider boundary
│   ├── slots/               # pure slot generation (DST-correct)
│   ├── bookings/            # create / cancel / reschedule + models
│   └── public/              # /{u}/{s}, /{u}/{s}/slots, /{u}/{s}/bookings
├── migrations/versions/     # 9 Alembic revisions
├── tests/                   # 96 integration tests (real Postgres)
├── docs/
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── DEVELOPMENT.md
│   └── KNOWN_ISSUES.md
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── pyproject.toml
├── package.json
└── Makefile
```

---

## Docs Index

- Product requirements: `PRD.md`
- Architecture & domain model: `docs/ARCHITECTURE.md`
- Full API reference: `docs/API.md`
- Development guide (setup, workflows, debugging): `docs/DEVELOPMENT.md`
- Known issues & gaps: `docs/KNOWN_ISSUES.md`
- Agent docs: `docs/agents/domain.md` · `docs/agents/issue-tracker.md` · `docs/agents/triage-labels.md`

---

## Known Issues & Gaps

> This section is duplicated in `docs/KNOWN_ISSUES.md` — the canonical list. A short summary:

- **No frontend** — API only by design.
- **No notifications** — invitees get `management_token` only once; if lost, no recovery email exists.
- **No calendar sync / conferencing / buffers / multi-event types** — all out of scope per PRD.
- **`package.json` lint script** was `ruff check .` without `--fix`; `yarn run lint --fix` previously did nothing (now fixed via `lint:fix`).
- **`.env.example` previously omitted `TEST_DATABASE_URL`** (now documented).
- **No Docker path** existed — fresh machines without local Postgres failed at `createdb` (now `docker-compose.yml` + `Dockerfile` added).
- **`btree_gist` requires superuser** on some hosted Postgres; mitigated by migration `CREATE EXTENSION IF NOT EXISTS` but may need manual intervention on managed DBs.
- **No mypy / type-check CI** yet.
- **No rate limiting or CORS config** — add before public exposure.
- See `docs/KNOWN_ISSUES.md` for the full list with severity and next steps.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Tests must run against the meet_scheduler_test database` | `createdb meet_scheduler_test` and set `TEST_DATABASE_URL` with that DB name; tests refuse any other name. |
| `connection refused` on `alembic upgrade head` / `uvicorn` | Postgres not running — `brew services start postgresql@14` or `docker compose up -d db`. |
| `alembic upgrade head` fails `btree_gist` / permission denied | DB user must be superuser (local `postgres` is). On managed DBs, create extension as superuser: `psql $DATABASE_URL -c 'CREATE EXTENSION IF NOT EXISTS btree_gist'`. |
| `role "postgres" does not exist` | Your local PG user is your OS user. Set `DATABASE_URL=postgresql+psycopg://<you>@localhost:5432/meet_scheduler` or create role: `createuser -s postgres`. |
| `yarn run lint --fix` does nothing | Use `yarn run lint:fix` or `.venv/bin/ruff check . --fix` (fixed in this repo). |
| `401 Could not validate credentials` | Access token expired (15 min) — `POST /auth/refresh` with the refresh token; refresh tokens are single-use. |
| `slot_no_longer_available` immediately after reading slots | Another invitee booked it, or `now + minimum_notice` / `horizon_days` excludes it. Re-fetch `GET …/slots` and re-check notice/horizon. |
| Docker: `port 5432 already allocated` | Stop local PG: `brew services stop postgresql@14 && docker compose up -d`. |
| FastAPI `on_startup` TypeError | Starlette/FastAPI version skew — reinstall: `.venv/bin/pip install -e ".[dev]"` (pins `fastapi>=0.115`, `starlette` compat). |
| Invitee lost `management_token` | No recovery flow exists (known gap) — host can cancel via `GET /bookings` + direct DB lookup; future work is email recovery. |

If you hit something not listed, open an issue with repro steps and attach `pytest -q` output and `alembic current`.

---

## License

Internal project — not yet licensed for external distribution.
