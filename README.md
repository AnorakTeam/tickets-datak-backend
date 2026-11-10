# Support Ticket Management Backend API
## Academic Project: API-DATAK (2026-2)

REST API built with **Django 6**, **Django REST Framework (DRF)**, **SimpleJWT**, and **PostgreSQL 16**.

---

## 1. Quick Start

### Prerequisites
- Python ≥ 3.12 (or `uv` package manager)
- Docker & Docker Compose (for PostgreSQL 16)

### Local Setup
```bash
# 1. Clone repository & checkout develop
git checkout develop

# 2. Create virtual environment & install dependencies
uv venv --python 3.12
source .venv/bin/activate
uv pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env

# 4. Start local PostgreSQL database container
docker compose up -d db

# 5. Run migrations
python manage.py migrate

# 6. Start local development server
python manage.py runserver 0.0.0.0:8000
```

---

## 2. Testing & Quality Checks

```bash
# Run Django system checks
python manage.py check

# Run automated tests
pytest

# Run linter and formatting checks
ruff check .
ruff format --check .
```

---

## 3. Core Documentation & Guides

- [`AGENTS.md`](./AGENTS.md): Operational instructions and guidelines for AI agents and developers.
- [`ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md`](./ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md): Full ERD, 20-field ticket model, and REST API v1 contracts.
- [`GIT_GITHUB_WORKFLOW_GUIDE.md`](./GIT_GITHUB_WORKFLOW_GUIDE.md): Git branching model, Conventional Commits, and PR rules.
- [`SPRINT_1_PLANNING_AND_SCHEDULE.md`](./SPRINT_1_PLANNING_AND_SCHEDULE.md): Sprint 1 tasks, dependencies, and target dates.
