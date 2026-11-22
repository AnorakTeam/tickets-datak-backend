# Postman Collections (Iteration 1 & Iteration 2)

## Iteration 1 Collection (`iteration_1_collection.json`)
The collection exercises the client-facing Iteration 1 endpoints in sequence:
1. Login with JWT
2. List active contracted modules
3. Create a client ticket
4. List the client's tickets
5. Get the created ticket's detail
6. Send a chatbot status message

## Iteration 2 Collection (`iteration_2_collection.json`)
The collection exercises the internal Support Console and client notification endpoints in sequence (RF7–RF16):
1. Login Support Agent (`agente@datak.co`)
2. List Active Companies (`GET /api/v1/support/empresas/`)
3. External Ticket Registration via WhatsApp (`POST /api/v1/support/tickets/`)
4. Unified Support Inbox (`GET /api/v1/support/tickets/`)
5. Support Ticket Detail & Full Audit History (`GET /api/v1/support/tickets/{radicado}/`)
6. Classify & Prioritize Incident (`PATCH /api/v1/support/tickets/{id}/clasificar/`)
7. Available Responsables Catalog (`GET /api/v1/support/responsables/`)
8. Assign Ticket to Engineer (`PATCH /api/v1/support/tickets/{id}/asignar/`)
9. Login Assigned Engineer (`responsable@datak.co`)
10. Engineer Queue - Mis Tickets (`GET /api/v1/support/mis-tickets/`)
11. Add Private Internal Note (`POST /api/v1/support/tickets/{id}/notas-internas/`)
12. Resolve Ticket & Trigger Notifications (`POST /api/v1/support/tickets/{id}/resolver/`)
13. Client Portal Notifications Feed (`GET /api/v1/client/notificaciones/`)
14. Mark Notification as Read (`PATCH /api/v1/client/notificaciones/{id}/leida/`)

## Run locally

Start PostgreSQL and the Django API following the repository's local setup instructions. Then apply migrations and load the idempotent development data:

```powershell
python manage.py migrate
python manage.py seed_data
python manage.py runserver
```

In another terminal, run:

```powershell
newman run docs/postman/iteration_1_collection.json -e docs/postman/dev_env.json
newman run docs/postman/iteration_2_collection.json -e docs/postman/dev_env.json
```

The environment targets `http://127.0.0.1:8000` and uses the local seed account `cliente@acme.com` / `test123456`, documented in `apps/core/management/commands/seed_data.py`. This is a development-only credential; do not reuse it outside a local seeded database. Change `base_url` and the client credentials in a private local Postman environment when testing another instance. The tracked environment does not contain production or personal credentials.
