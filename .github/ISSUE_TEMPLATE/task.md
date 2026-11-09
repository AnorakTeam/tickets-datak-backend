---
name: Engineering Task (Backend)
about: Granular engineering task for backend models, endpoints, services, or test suites
title: '[BE-TASK] <Short Description in English>'
labels: ['task', 'backend']
assignees: ''
---

### 1. Task Metadata & Traceability
- **Parent User Story:** Closes part of #<issue-number>
- **Project Schedule Task ID:** Task <ID> (from `API-DATAK.mpp`, e.g. Task 34, 37, 40, 47, 50, 57, 60, 63, 71)
- **Assigned Developer:** @<username> (`@AnorakTeam`, `@dannieltom`, `@sansviex`, `@tohond`)
- **Iteration:** Iteration 1 | Iteration 2

---

### 2. Objective & Description
<!-- Provide a clear, actionable summary of what needs to be implemented in the backend and why -->

---

### 3. Technical Specifications & Constraints
- **Target App / Directory:** `apps/<app_name>/` or `core/`
- **Database / Schema:**
  - Table name(s): `empresa`, `usuario`, `modulo_contratado`, `ticket`, `ticket_item`, `ticket_notificacion`
  - Relevant constraints: (e.g. `radicado` UNIQUE `TK-AAAA-NNNNNN`, `ticket.empresa_id == creado_por.empresa_id`, CHECK constraints)
- **API Contracts:**
  - Method: `GET | POST | PATCH | DELETE`
  - Route: `/api/v1/...`
  - Auth: `Bearer <JWT>`
  - Roles allowed: `cliente | agente_soporte | responsable_atencion`
- **Target Files:**
  - `path/to/models.py`
  - `path/to/serializers.py`
  - `path/to/views.py`
  - `path/to/services.py`
  - `tests/test_...py`

---

### 4. Acceptance Criteria & Deliverables
- [ ] Core model / migration / service logic implemented.
- [ ] ViewSet or endpoint exposed and secured with role-based permission classes.
- [ ] Multi-tenant scoping verified (clients never see other companies' data).
- [ ] Pytest unit and integration tests written and passing (coverage >= 80%).
- [ ] Code formatted and linted with `ruff`.

---

### 5. Verification Command
<!-- Command to verify the task locally -->
```bash
pytest tests/test_<module>.py -v
```
