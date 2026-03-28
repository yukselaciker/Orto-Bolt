# AGENTS.md

## Project Snapshot

This repository currently contains three connected surfaces:

- Desktop app: PySide6 + PyVista launcher rooted at `main.py` and `run.sh`
- Backend API: FastAPI app at `backend/app/main.py`
- Web UI: Next.js 14 app in `web/`

The shared Bolton calculation source of truth is `core/bolton_logic.py`. Keep desktop, backend, and web-facing behavior aligned with that module instead of reimplementing formulas in multiple places.

## Important Paths

- `main.py`: desktop Qt application entrypoint
- `run.sh`: preferred macOS launcher; configures Qt paths and can self-repair PySide6
- `scripts/dev_run.py`: desktop autoreload loop for Python/QSS/JSON changes
- `scripts/`: desktop helper utilities such as autoreload, Qt health check, and venv repair
- `core/`: shared STL loading, measurements, and Bolton logic
- `ui/`: desktop widgets and viewer code
- `reports/`: PDF/CSV/export helpers
- `backend/app/`: FastAPI routes, schemas, and services
- `backend/tests/test_api.py`: backend regression test coverage
- `web/`: Next.js frontend
- `session_data/`: local patient/session data; treat as user data

## Setup

Python dependencies are not guaranteed to be installed in a fresh checkout. Set up the Python environment before running desktop or backend commands:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt
```

Frontend setup:

```bash
cd web
npm install
cp .env.example .env.local
```

## Primary Workflows

### 1. Run the desktop app

Prefer the launcher script over calling `python main.py` directly:

```bash
./run.sh
```

Why: `run.sh` repairs outdated virtualenv entrypoints after folder moves, configures Qt plugin paths on macOS, runs `scripts/qt_healthcheck.py`, and attempts a pinned PySide6 reinstall if Qt fails to start.

### 2. Run the desktop app in autoreload mode

```bash
./run.sh --dev
```

This starts `scripts/dev_run.py`, which watches:

- `main.py`
- `ui/**/*.py`
- `core/**/*.py`
- `reports/**/*.py`
- `ai/**/*.py`
- supported `*.qss` files
- `*.json` files inside the watched app directories

### 3. Run the backend API

From the repo root with the Python venv active:

```bash
uvicorn backend.app.main:app --reload
```

Default local API URL:

```text
http://127.0.0.1:8000
```

Useful endpoints:

- `GET /health`
- `GET /api/v1/metadata`
- `POST /api/v1/analysis/anterior`
- `POST /api/v1/analysis/overall`
- `POST /api/v1/analysis/combined`
- `POST /api/v1/mesh/info`
- `POST /api/v1/export/json`
- `POST /api/v1/export/csv`
- `POST /api/v1/export/pdf`

### 4. Run the web app

```bash
cd web
npm run dev
```

The frontend reads:

```bash
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

Set that in `web/.env.local` when the backend is not running on the default host/port.

### 5. Run the full stack locally

Use separate terminals:

```bash
source .venv/bin/activate && uvicorn backend.app.main:app --reload
```

```bash
cd web && npm run dev
```

Open the Next.js app on `http://localhost:3000`.

## Validation Commands

Run these after installing dependencies:

### Python / backend

```bash
source .venv/bin/activate
python -m unittest backend.tests.test_api
```

### Qt startup smoke check

```bash
source .venv/bin/activate
python scripts/qt_healthcheck.py
```

### Frontend lint

```bash
cd web
npm run lint
```

### Frontend production build

```bash
cd web
npm run build
```

## Repo-Specific Notes For Agents

- Prefer editing shared business logic in `core/` first, then adapt API/UI layers around it.
- If a desktop launch fails on macOS, try `./run.sh` before deeper Qt debugging.
- Do not assume Python dependencies are installed; this workspace currently may lack `fastapi` and `PySide6` in the system interpreter.
- Treat `session_data/` as real working data. Avoid deleting or bulk-rewriting it unless the user explicitly asks.
- The frontend currently has package scripts for `dev`, `build`, `start`, and `lint`. Do not invent `test` or `typecheck` commands unless you add them.
- The backend allows CORS for `http://localhost:3000` and `http://127.0.0.1:3000`.
- This workspace is not currently a Git repository, so git-based workflows may be unavailable unless the user reconnects it to a repo.
