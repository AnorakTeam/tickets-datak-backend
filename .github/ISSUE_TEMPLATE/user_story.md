---
name: User Story (Backend)
about: Functional user story template for backend service capabilities
title: '[BE-US] HU-<ID>: <Short English Title>'
labels: ['user-story', 'backend']
assignees: ''
---

### 1. User Story Statement
**As a** [user role: Client / Support Agent / Assigned Developer]  
**I want to** [backend capability, endpoint, or business logic]  
**So that** [business value, traceability, or security benefit]  

---

### 2. Traceability & Scope
- **Project Deliverable:** E1 (Software MVP)
- **Iteration:** Iteration 1 | Iteration 2
- **Functional Requirements (RF):** RF<XX> (e.g. RF1, RF2, RF7, RF8, etc.)
- **Non-Functional Requirements (RNF):** 
  - RNF2 (Multi-tenancy isolation & Role-based permissions)
  - RNF3 (Pagination, no N+1 queries, response < 2s)
  - RNF5 (Immutable audit trail on `TicketItem`)
  - RNF8 (Pytest coverage & Postman collection)

---

### 3. Acceptance Criteria (Gherkin Scenarios)
#### Scenario 1: Successful Execution (Happy Path)
- **Given** an authenticated user with role `[cliente / agente_soporte / responsable_atencion]`
- **When** request is made to `[HTTP METHOD] /api/v1/[endpoint]`
- **Then** status code `[200 / 201]` is returned with expected payload and database state updated

#### Scenario 2: Multi-Tenant Isolation Enforcement
- **Given** an authenticated client user from Company A
- **When** querying or accessing a resource belonging to Company B
- **Then** status code `404 Not Found` is returned without leaking existence

#### Scenario 3: Role-based Authorization / Boundary Failure
- **Given** a user without the required permissions or invalid payload
- **When** the operation is submitted
- **Then** status code `403 Forbidden` or `400 Bad Request` is returned with descriptive error message

---

### 4. Technical Checklist
- [ ] Database model and migrations created/updated (`empresa`, `usuario`, `modulo_contratado`, `ticket`, `ticket_item`, `ticket_notificacion`)
- [ ] Domain services, state transitions, and selectors implemented
- [ ] Serializers configured (differentiating client views from internal console views)
- [ ] DRF ViewSet / APIView registered under `/api/v1/`
- [ ] Pytest unit and integration tests added (isolation, permissions, status transitions)
- [ ] Postman collection updated
