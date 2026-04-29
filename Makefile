.PHONY: setup dev-api dev-mock-abha dev-web dev-fhir db-migrate cohort-seed terminology-seed fhir-seed demo-reset demo-health demo-smoke demo-prep test lint help

help:
	@echo "Smriti Monorepo - Available commands:"
	@echo ""
	@echo "  setup                - Initial setup: install dependencies for all Python apps"
	@echo "  dev-api              - Run smriti-api dev server (port 8000)"
	@echo "  dev-mock-abha        - Run mock-abha dev server (port 8001)"
	@echo "  dev-web              - Run smriti-web dev server (port 3000)"
	@echo "  dev-fhir             - Spin up HAPI FHIR server via Docker Compose"
	@echo "  db-migrate           - Run database migrations"
	@echo "  cohort-seed          - Generate synthetic patient cohort"
	@echo "  terminology-seed     - Load SNOMED/LOINC/ICD-10/RxNorm subsets"
	@echo "  fhir-seed            - Load Priya's Apollo cardiac history into HAPI FHIR + Smriti"
	@echo "  demo-reset           - Reset DB, re-run migrations/seeds, and cache Priya demo briefings"
	@echo "  demo-health          - Validate all demo dependencies"
	@echo "  demo-smoke           - Run end-to-end demo simulation assertions"
	@echo "  demo-prep            - Full demo preparation: reset, health check, cache briefings"
	@echo "  test                 - Run tests for all Python packages"
	@echo "  lint                 - Run linters (ruff, black, mypy)"

setup:
	@echo "Setting up Smriti monorepo..."
	cd apps/smriti-api && uv sync
	cd apps/mock-abha && uv sync
	@echo "Setup complete! Run 'make dev-api' to start the API."

dev-api:
	@echo "Starting Smriti API (port 8000)..."
	cd apps/smriti-api && uv run --env-file ../../.env python -m uvicorn smriti.main:app --host 0.0.0.0 --port 8000 --reload

dev-mock-abha:
	@echo "Starting Mock ABHA service (port 8001)..."
	cd apps/mock-abha && uv run python -m uvicorn mock_abha.main:app --host 0.0.0.0 --port 8001 --reload

dev-web:
	@echo "Starting Next.js web interface (port 3000)..."
	-@powershell -Command "$$p = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if ($$p) { Stop-Process -Id $$p -Force }"
	cd apps/smriti-web && npm run dev

dev-fhir:
	@echo "Starting HAPI FHIR server via Docker Compose..."
	docker-compose up -d hapi-fhir
	@echo "FHIR server running at http://localhost:8082/fhir"

db-migrate:
	@echo "Running database migrations..."
	python -m uv run --project apps/smriti-api --env-file .env python -m smriti.db.migrate

cohort-seed:
	@echo "Generating synthetic patient cohort..."
	python -m uv run --project apps/smriti-api --env-file .env python scripts/generate_cohort.py

terminology-seed:
	@echo "Loading SNOMED/LOINC/ICD-10/RxNorm subsets..."
	python -m uv run --project apps/smriti-api --env-file .env python scripts/load_terminology.py

fhir-seed:
	@echo "Seeding Priya's Apollo cardiac history into MockHospital HAPI FHIR + Smriti..."
	cd apps/smriti-api && uv run python -m smriti.integrations.mock_hospital_loader

demo-reset:
	@echo "Resetting demo state (drop schema + migrations + seeds + Priya cache)..."
	python -m uv run --project apps/smriti-api --env-file .env python apps/smriti-api/scripts/demo_reset.py
	$(MAKE) db-migrate
	$(MAKE) terminology-seed
	$(MAKE) cohort-seed
	python -m uv run --project apps/smriti-api --env-file .env python apps/smriti-api/scripts/cache_demo_briefing.py

demo-health:
	@echo "Running demo dependency checks..."
	python -m uv run --project apps/smriti-api --env-file .env python apps/smriti-api/scripts/demo_health.py

demo-smoke:
	@echo "Running full demo smoke simulation..."
	python -m uv run --project apps/smriti-api --env-file .env python apps/smriti-api/scripts/demo_smoke.py

demo-prep: demo-reset demo-health
	@echo "Refreshing cached demo briefings..."
	python -m uv run --project apps/smriti-api --env-file .env python apps/smriti-api/scripts/cache_demo_briefing.py

test:
	@echo "Running tests for smriti-api..."
	cd apps/smriti-api && uv run pytest tests/
	@echo "Running tests for mock-abha..."
	cd apps/mock-abha && uv run pytest tests/

lint:
	@echo "Running linters..."
	@echo "Linting smriti-api..."
	cd apps/smriti-api && uv run ruff check src/ tests/
	cd apps/smriti-api && uv run black --check src/ tests/
	cd apps/smriti-api && uv run mypy src/
	@echo "Linting mock-abha..."
	cd apps/mock-abha && uv run ruff check src/ tests/
	cd apps/mock-abha && uv run black --check src/ tests/
