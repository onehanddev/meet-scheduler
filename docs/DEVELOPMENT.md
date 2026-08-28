# Development Guide

This is the exhaustive guide to getting the project running correctly on any machine, plus workflows for iterating, testing, and debugging.

## Prerequisites

- Python **3.12+** (`python3 --version` must show `3.12.x`). Recommended: `pyenv`.
- PostgreSQL **16** (or Docker — the `docker-compose.yml` ships with the repo).
- `git`, `make` (optional), `psql` client (for ad-hoc inspection).
- Node/Yarn only for `yarn run lint` (alias for `ruff check`).

### Python 3.12 via pyenv (macOS/Linux)

```bash
brew install pyenv   # or: curl https://pyenv.run | bash
pyenv install 3.12
pyenv local 3.12
python3 --version  # 3.12.x
```

Windows: use WSL2 and follow Linux steps, or use Docker path below (no local Postgres needed).

## Setup — Two Paths

### Path A — Local Postgres (fastest for iteration)

```bash
git clone <repo-url> meet-scheduler && cd meet-scheduler

# 1) venv + deps
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2) databases
brew services start postgresql@14    # or postgresql@16, match your Homebrew
createdb meet_scheduler
createdb meet_scheduler_test         # TEST DB NAME MUST BE meet_scheduler_test

# 3) env
cp .env.example .env
# Optionally edit .env: DATABASE_URL, TOKEN_SECRET
# Generate a strong TOKEN_SECRET for real use:
#   python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# 4) migrate
alembic upgrade head
alembic current   # should show the head revision (20260828_09…)

# 5) verify
pytest -q
uvicorn meet_scheduler.main:app --reload
# → http://127.0.0.1:8000/docs
```

Shorthand via Make: `make install && make db-create && make migrate && make test`.

### Path B — Docker (no local Postgres required)

```bash
git clone <repo-url> meet-scheduler && cd meet-scheduler
cp .env.example .env
docker compose up -d --build
# DB is at db:5432 inside compose; host is mapped to 5432 as well
# If you run the API on the host, keep DATABASE_URL pointing at localhost:
alembic upgrade head
pytest -q          # TEST_DATABASE_URL defaults to localhost, works if compose DB is up
uvicorn meet_scheduler.main:app --reload
# Or run the API inside compose: docker compose logs -f api
```

`docker-compose.yml` details:
- `db`: `postgres:16-alpine`, `postgres:postgres`, `meet_scheduler`, `5432:5432`, `pgdata` volume, healthcheck `pg_isready`.
- `api`: builds `Dockerfile` (python 3.12-slim, gcc/libpq-dev, `-e .[dev]`), mounts `.:/app`, `uvicorn --host 0.0.0.0 --reload`.
- `docker compose down` removes containers but keeps `pgdata`; `docker compose down -v` wipes data.

## Environment

| Var | Required | Where | Notes |
|---|---|---|---|
| `APP_ENV` | no | `.env`, `config.py` | Defaults `development`. |
| `DATABASE_URL` | yes | `.env`, `config.py`, `alembic.ini` fallback | API + Alembic. In compose, use `@db:5432`. |
| `TEST_DATABASE_URL` | tests only | `.env` / shell override | Default `…/meet_scheduler_test`. **Must end in `meet_scheduler_test`** or tests abort. Override: `TEST_DATABASE_URL=… pytest -q`. |
| `TOKEN_SECRET` | yes | `.env` | HS256 secret. Don’t commit a real secret. |

`config.py:Settings` is `pydantic-settings` (`env_file=.env`). Alembic’s `alembic.ini` carries a localhost fallback but the live URL is `DATABASE_URL` from env when invoked via app config.

## Migrations

```bash
alembic upgrade head       # apply all
alembic downgrade base     # revert all
alembic current            # show current revision
alembic history            # log of 9 revisions (20260828_01 → 09)
# new migration
alembic revision -m "add something"
# then edit migrations/versions/<rev>_<slug>.py (upgrade/downgrade)
```

Key migration: `20260828_07` — `CREATE EXTENSION IF NOT EXISTS btree_gist` + `EXCLUDE USING gist` on `bookings`. Requires Postgres superuser (`postgres` role is superuser locally and in compose).

## Running the API

```bash
uvicorn meet_scheduler.main:app --reload      # host
# or
make api
# or
docker compose up -d && docker compose logs -f api
```

Endpoints:
- `GET /healthz` — health
- `GET /docs`, `GET /redoc`, `GET /openapi.json` — OpenAPI
- See `docs/API.md` for the full reference and `README.md` for curl examples.

## Testing

```bash
pytest -q                 # all 96 tests
pytest -v -k test_slots   # filter by name
pytest --collect-only -q  # list without running
TEST_DATABASE_URL=postgresql+psycopg://…/meet_scheduler_test pytest -q  # override URL
```

How tests work (`tests/conftest.py`):
- Fixture `session_factory` creates an engine to `TEST_DATABASE_URL`, asserts `database == "meet_scheduler_test"`, does `alembic downgrade base → upgrade head`, yields a `sessionmaker`, then tears down (`downgrade base`) at session end.
- `client` fixture builds `Settings(_env_file=None, database_url=TEST_DATABASE_URL, token_secret="test-token-secret-that-is-long-enough")` and `create_app(settings, session_factory)`.
- Clock is patched via `unittest.mock.patch("meet_scheduler.slots.service.get_now", return_value=…)`.

DB inspection during development:

```bash
psql postgresql://postgres:postgres@localhost:5432/meet_scheduler -c "\dt"
psql postgresql://postgres:postgres@localhost:5432/meet_scheduler_test -c "\dt"
psql $DATABASE_URL -c "SELECT email, username FROM hosts LIMIT 5;"
psql $DATABASE_URL -c "SELECT status, start_time FROM bookings LIMIT 5;"
```

## Lint & Checks

```bash
yarn run lint        # ruff check .        (via package.json)
yarn run lint:fix    # ruff check . --fix
.venv/bin/ruff check .           # direct (no yarn)
.venv/bin/ruff check . --fix
.venv/bin/pytest -q
```

Ruff config: `pyproject.toml` (`line-length=88`, `target-version=py312`, `select=E,F,I,UP,B`). No mypy enforced yet (see Known Issues).

Pre-commit (optional):
```bash
# .git/hooks/pre-commit
#!/bin/sh
.venv/bin/ruff check . || exit 1
.venv/bin/pytest -q || exit 1
```

## Common Workflows

### Add a new endpoint
1. Add Pydantic schemas in `<module>/schemas.py`.
2. Add router factory in `<module>/router.py` (`create_*_router(get_session, get_settings)`).
3. Register it in `main.py:create_app` (`app.include_router(create_*(get_session, resolve_settings))`).
4. Add model fields/migration if needed.
5. Write an API-level test in `tests/<area>/test_*.py` using `client` fixture + `session_factory`.

### Patch a module
- Keep `dependencies.create_current_host_dependency` as the single auth seam.
- Availability/host/meeting-type writes lock the host `FOR UPDATE`; booking reads use `FOR KEY SHARE` / `FOR SHARE` — see `docs/ARCHITECTURE.md`.

### Reset DB
```bash
alembic downgrade base && alembic upgrade head
# or nuke (local):
dropdb meet_scheduler && createdb meet_scheduler && alembic upgrade head
# or (docker):
docker compose down -v && docker compose up -d --build && alembic upgrade head
```

## Debugging

- **Validation errors**: FastAPI returns `422` with `details[{field,message}]` from `main.handle_validation_error`. Log payloads at router level, never log raw passwords/tokens.
- **Auth 401s**: decode JWT locally: `python3 -c "import jwt; print(jwt.decode(token, key, algorithms=['HS256']))"`.
- **Booking conflicts**: check `psql -c "SELECT * FROM pg_stat_activity"` or run the concurrent tests verbosely: `pytest tests/public/test_bookings.py -v`.
- **DST edge cases**: see `tests/public/test_slots.py:152-191` and `slots/service.py:_host_local_to_utc`.
- **Lock contention**: the concurrency tests in `tests/public/test_bookings.py` use `pg_blocking_pids` to assert real DB contention.

## Verifying a Clean Checkout

Run this checklist after any fresh clone:

```bash
python3 --version  # ≥3.12
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env
createdb meet_scheduler 2>/dev/null; createdb meet_scheduler_test 2>/dev/null
# or: docker compose up -d --build
alembic upgrade head
pytest -q           # 96 passed
.venv/bin/ruff check .  # All checks passed!
uvicorn meet_scheduler.main:app --reload  # curl http://127.0.0.1:8000/healthz
```
