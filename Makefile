.DEFAULT_GOAL := help
DC := docker compose -p vpnhub-dev
DB_URL := postgresql+asyncpg://vpnhub:secret@localhost:5433/vpnhub

help: ##@ Показать список целей
	@grep -hE '^[a-zA-Z0-9_-]+:.*##@' $(MAKEFILE_LIST) | sed 's/:.*##@/\t/' | sort

## ---- backend ----
install: ##@ Установить зависимости (backend + frontend)
	cd backend && uv sync
	cd frontend && npm install

fmt: ##@ Формат + автофикс (ruff)
	cd backend && uv run ruff format . && uv run ruff check --fix .

check: ##@ Проверки (ruff + mypy, read-only)
	cd backend && uv run ruff format --check . && uv run ruff check . && uv run mypy src

test: ##@ Прогнать тесты (pytest; in-memory SQLite, без внешней инфры)
	cd backend && uv run --no-sync pytest

test-unit: ##@ Только unit-тесты (чистая логика)
	cd backend && uv run --no-sync pytest -m unit

migrate: ##@ Накатить миграции (alembic upgrade head)
	cd backend && DATABASE_URL=$(DB_URL) uv run alembic upgrade head

migration: ##@ Сгенерировать миграцию: make migration m="..."
	cd backend && DATABASE_URL=$(DB_URL) uv run alembic revision --autogenerate -m "$(m)"

run: ##@ Запустить backend (uvicorn, reload)
	cd backend && DATABASE_URL=$(DB_URL) VPNHUB_DOCS_ENABLED=1 uv run uvicorn vpnhub.api.entrypoint:create_app --factory --reload --port 8000

## ---- frontend ----
front-dev: ##@ Vite dev-сервер (proxy /api → :8000)
	cd frontend && npm run dev

front-build: ##@ Собрать фронт и положить в статику backend
	cd frontend && npm run build
	rm -rf backend/src/vpnhub/static && mkdir -p backend/src/vpnhub/static
	cp -r frontend/dist/* backend/src/vpnhub/static/

changelog: ##@ Сгенерировать CHANGELOG.md из курируемого источника (backend/.../infra/changelog.py)
	cd backend && uv run python ../scripts/gen_changelog.py

front-lint: ##@ Тайпчек фронта
	cd frontend && npx tsc --noEmit

## ---- infra ----
db-up: ##@ Поднять локальный Postgres (docker)
	docker run -d --name vpnhub-pg -e POSTGRES_DB=vpnhub -e POSTGRES_USER=vpnhub -e POSTGRES_PASSWORD=secret -p 5433:5432 postgres:17

db-down: ##@ Остановить локальный Postgres
	docker rm -f vpnhub-pg

build: ##@ Собрать docker-образ продукта
	docker build -t vpnhub:dev .

hadolint: ##@ Линт Dockerfile (тот же .hadolint.yaml, что и в CI)
	docker run --rm -i -v "$(CURDIR)/.hadolint.yaml:/.hadolint.yaml:ro" \
		hadolint/hadolint hadolint --config /.hadolint.yaml --failure-threshold warning - < Dockerfile

## ---- docs ----
docs-serve: ##@ Локальный предпросмотр документации (zensical serve)
	cp CHANGELOG.md docs/changelog.md
	uv run --project backend --no-dev --group docs zensical serve

docs-build: ##@ Собрать сайт документации в site/ (zensical build)
	cp CHANGELOG.md docs/changelog.md
	uv run --project backend --no-dev --group docs zensical build --clean

## ---- demo media (скриншоты и промо-ролик; см. tools/demo/README.md) ----
demo-up: ##@ Изолированный demo-инстанс (БД vpnhub_demo) для скринов/ролика
	./tools/demo/run-demo-backend.sh

screenshots: ##@ Снять скриншоты доков (нужен запущенный demo-up)
	cd tools/demo && node screenshots/capture.mjs

reel: ##@ Собрать промо-ролик в docs/assets/reel (нужен запущенный demo-up)
	cd tools/demo && node reel/gen-assets.mjs && node reel/record.mjs && bash reel/compose.sh

.PHONY: help install fmt check test test-unit migrate migration run front-dev front-build front-lint db-up db-down build hadolint docs-serve docs-build demo-up screenshots reel
