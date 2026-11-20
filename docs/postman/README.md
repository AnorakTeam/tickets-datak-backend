# Iteration 1 Postman collection

The collection exercises the client-facing Iteration 1 endpoints in sequence:

1. Login with JWT
2. List active contracted modules
3. Create a client ticket
4. List the client's tickets
5. Get the created ticket's detail
6. Send a chatbot status message

The tests validate each endpoint's HTTP status and response shape. Variables returned by login, module listing, and ticket creation are saved for later requests. The client detail assertions also ensure internal staff and audit fields are not exposed.

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
```

The environment targets `http://127.0.0.1:8000` and uses the local seed account `cliente@acme.com` / `test123456`, documented in `apps/core/management/commands/seed_data.py`. This is a development-only credential; do not reuse it outside a local seeded database. Change `base_url` and the client credentials in a private local Postman environment when testing another instance. The tracked environment does not contain production or personal credentials.
