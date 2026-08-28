.PHONY: install db-create migrate lint test api docker-up docker-down clean

install:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

db-create:
	createdb meet_scheduler 2>/dev/null || echo "meet_scheduler already exists"
	createdb meet_scheduler_test 2>/dev/null || echo "meet_scheduler_test already exists"

migrate:
	alembic upgrade head

lint:
	.venv/bin/ruff check .

lint-fix:
	.venv/bin/ruff check . --fix

test:
	.venv/bin/pytest -q

api:
	.venv/bin/uvicorn meet_scheduler.main:app --reload

docker-up:
	docker compose up -d --build
	docker compose exec db bash -c "until pg_isready -U postgres; do sleep 0.5; done"
	docker compose exec api alembic upgrade head || .venv/bin/alembic upgrade head

docker-down:
	docker compose down

clean:
	rm -rf .venv .pytest_cache .ruff_cache __pycache__ .coverage htmlcov dist build *.egg-info

setup: install
	cp -n .env.example .env 2>/dev/null || true
	@echo "== Next: create DBs and migrate =="
	@echo "  make db-create   # or: make docker-up (if you prefer Docker)"
	@echo "  make migrate"
	@echo "  make test"
