.PHONY: help setup backend web test lint build clean

PY := backend/.venv/bin/python
PIP := backend/.venv/bin/pip

help:
	@echo "make setup    - create the backend venv and install both sides"
	@echo "make backend  - run the FastAPI dev server on :8000"
	@echo "make web      - run the Vite dev server on :5173"
	@echo "make test     - backend unit tests"
	@echo "make lint     - ruff + eslint + tsc"
	@echo "make build    - production frontend build"

setup:
	python3 -m venv backend/.venv || true
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -r backend/requirements-dev.txt
	cd frontend && npm install
	@test -f backend/.env || cp backend/.env.example backend/.env
	@test -f frontend/.env.local || cp frontend/.env.example frontend/.env.local
	@echo "\nNow fill in backend/.env and frontend/.env.local, then run 'make backend' and 'make web'."

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest -q

lint:
	cd backend && .venv/bin/ruff check .
	cd frontend && npm run lint && npx tsc -b --noEmit

build:
	cd frontend && npm run build

clean:
	rm -rf frontend/dist frontend/node_modules/.vite backend/.pytest_cache backend/.ruff_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
