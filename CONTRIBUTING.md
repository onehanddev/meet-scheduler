# Contributing

## Getting Started

Read `README.md` (quickstart + features) and `docs/DEVELOPMENT.md` (full setup, migrations, testing, debugging).

Fresh machine checklist:
```bash
python3 --version  # 3.12+
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
cp .env.example .env
createdb meet_scheduler; createdb meet_scheduler_test  # or: docker compose up -d
alembic upgrade head
pytest -q && ruff check .
```

## Workflow

1. **Pick work** from `docs/KNOWN_ISSUES.md` or GitHub issues. Move to `in-progress`.
2. **Branch** from `main` (or current base): `git checkout -b issue-42-some-fix`.
3. **Code** inside one deep module seam where possible (`hosts/`, `meeting_types/`, `availability/`, `slots/`, `bookings/`, `public/`). Keep `dependencies.get_current_host` as the shared auth seam.
4. **Test** at the API level with real Postgres (`tests/` fixtures). Prefer contract/business assertions over implementation checks.
5. **Lint** `ruff check . --fix` (`yarn run lint:fix`) and `pytest -q` — both must pass before pushing.
6. **Commit** concise message, push, open PR with issue link.

## Code Style

- Follow existing patterns: CSS class conventions, icon usage, and component patterns already in the repo. Don’t recreate existing utilities.
- Use `ruff` config from `pyproject.toml` (E, F, I, UP, B, line-length 88, py312).
- Never commit `.env`, secrets, or `*.py[cod]` / `.venv/` / `.pytest_cache/` (already ignored).
- Logs must not contain passwords, hashes, tokens, or invitee PII.

## Migrations

```bash
alembic revision -m "add something"
# edit migrations/versions/<rev>_<msg>.py
alembic upgrade head
```
Keep `upgrade`/`downgrade` symmetric and safe on a clean DB.

## PR Checklist

- [ ] Tests added/updated and `pytest -q` green
- [ ] `ruff check .` green
- [ ] Updated relevant docs (`README.md` / `docs/*`) if behavior changed
- [ ] Moved `KNOWN_ISSUES.md` entry from Remaining → Fixed (if applicable)

## Reporting Issues

Open a GitHub issue with:
- Steps to reproduce (curl / test snippet)
- Expected vs actual behavior
- `pytest -q` output and `alembic current` if DB-related
