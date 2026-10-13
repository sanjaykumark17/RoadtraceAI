.PHONY: up down test migrate lint

up:
	docker compose up -d --build

down:
	docker compose down -v

test:
	cd backend && python -m pytest tests/ -v

migrate:
	cd backend && alembic upgrade head

lint:
	cd backend && python -m ruff check app/
