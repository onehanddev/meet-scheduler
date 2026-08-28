# Known Issues & Gaps

This is the canonical tracker of issues that are fixed, remaining, or intentionally out-of-scope. It was created as part of making the repo developer-friendly — so every contributor knows what still needs attention without reading `PRD.md` end-to-end.

> **Rule:** Before working on a remaining issue, open a GitHub issue, link to the relevant `TODO` below, and mark it `in-progress`. When fixed, move it to **Fixed** and keep the row (history matters).

---

## Fixed (this pass)

| # | Issue | Fix | PR/Commit |
|---|---|---|---|
| F1 | `yarn run lint --fix` was a no-op (script was `ruff check .` without `--fix`) | Added `lint:fix` (`ruff check . --fix`) in `package.json` | this pass |
| F2 | `.env.example` omitted `TEST_DATABASE_URL`; new machines got `Tests must run against…` with no guidance | Documented `TEST_DATABASE_URL` + generator for `TOKEN_SECRET` in `.env.example` | this pass |
| F3 | No Docker path — fresh machines without local Postgres failed at `createdb` | Added `docker-compose.yml` + `Dockerfile` + Make `docker-up/down` + README Option B | this pass |
| F4 | README was 52 lines, no product/feature/API/setup coverage | Rewrote `README.md` (features, stack, two quickstarts, env, migrations, API table, curl examples, slot rules, tests, layout, troubleshooting) | this pass |
| F5 | No architecture / API / dev guide | Added `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/DEVELOPMENT.md` | this pass |

## Remaining — Must Fix Before Production

| # | Severity | Issue | Detail / Next Step |
|---|---|---|---|
| R1 | **High** | **No rate limiting** | Public `POST /{u}/{s}/bookings` + auth endpoints are open to abuse. Add IP-based throttling (e.g. `slowapi` or reverse-proxy limit) before exposing publicly. |
| R2 | **High** | **No CORS config** | If a browser frontend is served from another origin, requests will be blocked. Add `CORSMiddleware` with explicit `allow_origins` in `main.create_app`. |
| R3 | **High** | **Management token is returned once with no recovery** | If an invitee loses the `management_token` there is no email “resend link” flow. Minimal fix: log or persist an opaque “send link” capability; full fix: email verification + resend endpoint. |
| R4 | **High** | **No mypy/type-check CI** | Tests pass but no static type enforcement. Add `mypy` (or `pyright`) + CI step. `pyproject.toml` has no `[tool.mypy]` yet. |
| R5 | **Medium** | **`btree_gist` requires superuser on managed Postgres** | Migration `20260828_07` does `CREATE EXTENSION IF NOT EXISTS btree_gist`; works locally and in compose (`postgres` is superuser) but fails on e.g. RDS with non-superuser role. Mitigation: document manual superuser step or use alternative constraint. |
| R6 | **Medium** | **No access-token revocation (JWT)** | `POST /auth/logout` revokes refresh token only; outstanding access tokens remain valid until 15 min expiry. Acceptable per PRD but document as known window. For stronger revocation, add a blocklist or shorten expiry. |
| R7 | **Medium** | **Tests require Postgres; no in-memory substitute** | Intentional per PRD (overlap constraint correctness) but means CI must provision Postgres. New contributors on Windows/macOS without Docker will hit `connection refused`. README now covers Docker path. |
| R8 | **Medium** | **No CI workflow yet** | Recommend `.github/workflows/ci.yml` running `ruff check .` + `pytest -q` against a Postgres service (see Development Guide checklist). |
| R9 | **Low** | **No seed/demo data** | `POST /auth/register` … `PUT /availability` is the happy-path seed. Consider `scripts/seed.py` for demos. |
| R10 | **Low** | **`alembic.ini` hardcodes localhost URL** | Fallback `sqlalchemy.url` in `alembic.ini` is `postgresql+psycopg://postgres:postgres@localhost/meet_scheduler`. Works locally but redundant with env `DATABASE_URL`. Consider templating or `alembic --url $DATABASE_URL`. Not a bug — just noted. |
| R11 | **Low** | **No pagination on `GET /bookings`** | Host with many bookings gets an unbounded list. Add `?limit&offset` or cursor before large-data use. |
| R12 | **Low** | **No `created_at`/`updated_at` DB defaults** | App sets these (`services: now()`). Ensure clock skew / bulk inserts keep them consistent if direct SQL use grows. |

## Intentionally Out-of-Scope (Not Bugs)

These are excluded per `PRD.md` § Out of Scope — listed here so they are not re-filed as issues:

- OAuth / magic-link / email verification / password reset / MFA / breached-password lookup
- Google Calendar / Outlook / Apple Calendar sync
- Email / SMS / push / webhook notifications or reminders
- Zoom / Google Meet / Teams / other conferencing links or physical locations
- Organizations, teams, round-robin / collective events, roles beyond host ownership
- More than one meeting type per host; multi-host or multi-invitee meetings
- Date-specific availability overrides / holidays / vacation blocks (architecture anticipates this via `WeeklyAvailabilityProvider` boundary — see `docs/ARCHITECTURE.md`)
- Host approval / tentative states / waitlists
- Payments / subscriptions / billing / usage limits
- Custom invitee questions / required phone / custom forms
- Buffers / travel time / daily limits / group capacity
- Username redirect history / custom domains
- Frontend / mobile / admin dashboard
- Importing historical bookings

## How to Contribute a Fix

1. Pick an `R#` above, or file a new GitHub issue with `backlog`.
2. Move it to `in-progress` when starting.
3. Add/adjust tests alongside code (API-level, real Postgres — see `docs/DEVELOPMENT.md`).
4. Keep changes inside one deep module seam where possible.
5. Run `ruff check . --fix` and `pytest -q` before pushing.
