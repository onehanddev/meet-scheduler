# Meet Scheduler

Minimal one-on-one meeting scheduler backend, inspired by Calendly and Cal.com.

## Stack

- Python 3.12
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- Pytest
- Ruff

## Local Development

Create a virtual environment and install the package with development dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Create the local databases and configure the environment:

```bash
createdb meet_scheduler
createdb meet_scheduler_test
cp .env.example .env
alembic upgrade head
```

Run the API:

```bash
uvicorn meet_scheduler.main:app --reload
```

Run checks:

```bash
yarn run lint --fix
pytest
```

Set `TEST_DATABASE_URL` to override the default local test database URL when
needed. Tests refuse to run against a database not named `meet_scheduler_test`.

## Product Spec

See `PRD.md` for the backend product requirements.
