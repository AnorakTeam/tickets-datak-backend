# AGENTS.md — Autonomous Agent Operating Directives (Backend)
## Repository: `tickets-datak-backend`

This document defines mandatory operational instructions, coding standards, domain invariants, and Git protocols for any AI agent or autonomous coding assistant operating within `tickets-datak-backend`.

---

## 1. Technical Stack & Standards

- **Framework:** Python ≥ 3.12, Django 6.0+, Django REST Framework (DRF) 3.17+.
- **Database:** PostgreSQL 16 (local development via `docker-compose.yml`).
- **Authentication:** `djangorestframework-simplejwt` (JWT Bearer tokens).
- **Testing:** `pytest`, `pytest-django`, `pytest-cov`.
- **Linting & Formatting:** `ruff` (run `ruff check .` and `ruff format .`).
- **Language Rules:**
  - **Code, documentation, Git:** Written strictly in **English** (variable names, docstrings, commit messages, PRs).
  - **Domain choices & notifications:** Catalog choices (`Abierto`, `En gestion`, `Resuelto`, `No procedente`), validation error messages, and transactional email bodies must be in **Spanish**.

---

## 2. Permitted Code Owners & Roles

Only authorized backend contributors may have their user handles assigned:
- `@AnorakTeam` (José Manuel Pérez — DevOps & Project Manager): Scaffolding, Docker, CI, code reviews, develop/main merges.
- `@dannieltom` (Juan Torres — Tech Lead & Backend): Core models (`Empresa`, `Usuario`, `Ticket` 20 fields, `TicketItem`), client ticket endpoints.
- `@sansviex` (Giovanny Muñoz — Backend Developer): Catalogs (`ModuloContratado`), seed data fixtures, atomic radicado generator, email service, report endpoint.
- `@tohond` (Omar Palencia — QA Lead & Backend): Chatbot state machine, Pytest multi-tenant isolation suite, Postman collection.

---

## 3. Strict Domain Invariants & Security Rules

1. **Multi-Tenancy Isolation (RNF2):**
   - The tenant boundary is `Empresa`.
   - The client's company is **never** accepted from incoming request payloads. It must be resolved strictly on the server: `request.user.empresa`.
   - Attempting to retrieve, update, or view a ticket from another company **MUST return HTTP 404 Not Found** (never 403, to prevent tenant ID enumeration).
2. **Client Information Hiding (RNF2):**
   - Client serializers (`ClientTicketDetailSerializer`, `ClientTicketListSerializer`) **strictly omit** assigned staff (`responsable`), internal notes (`TicketItem.es_interna = True`), and developer estimations.
3. **Audit Log Immutability (RNF5):**
   - The `TicketItem` model is insert-only (event sourcing).
   - Overwrite `save()` on existing instances and `delete()` to raise `PermissionDenied` or `ValidationError`.
   - No `PUT`, `PATCH`, or `DELETE` endpoints may be created for `TicketItem`.
4. **Ticket Model Conformance (FP8 Range MEDIO):**
   - The `Ticket` model must strictly maintain its **20 domain fields** as documented in [`ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md`](./ARCHITECTURE_AND_DATA_MODEL_REFERENCE.md). Do not delete or rename fields.
5. **Radicado Sequence Format:**
   - Format: `TK-YYYY-NNNNNN` (e.g. `TK-2026-000001`). Generated via atomic database transactions with row-level locks (`select_for_update`) to prevent race conditions.

---

## 4. Git & GitHub Project Workflow

1. **Base Branch:** Always branch off `develop` and target `develop` for Pull Requests:
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feat/<task-id>-<short-description>
   ```
2. **Project Card Transition:**
   - Before coding, move your task card from `Todo` to `In Progress` on [GitHub Project #1](https://github.com/users/AnorakTeam/projects/1).
3. **Conventional Commits:**
   ```bash
   git commit -m "feat(tickets): implement Ticket model with exact 20 fields"
   git commit -m "test(isolation): add multi-tenant cross-company 404 test suite"
   ```
4. **Pull Request Protocol:**
   - Title: `[BE-TASK] <TASK-ID>: <Title> (Closes #<issue-number>)`
   - Description must use `.github/pull_request_template.md` and include `Closes #<issue-number>` (this automatically moves the task to `In Review`).
5. **Strict No-Squash Merge Policy:**
   - Merging into `develop` or `main` must use **"Create a merge commit"** (`gh pr merge --merge`). Squash and rebase are strictly prohibited.

---

## 5. Verification Commands

Run these commands before opening any Pull Request:
```bash
# 1. Run migrations dry-run check
python manage.py makemigrations --check --dry-run

# 2. Run linting & formatting checks
ruff check .
ruff format --check .

# 3. Run full automated test suite
pytest

# 4. Verify seed data command
python manage.py seed_data
```
