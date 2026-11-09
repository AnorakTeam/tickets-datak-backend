## Summary
Brief description of the changes introduced in this pull request. Explain the problem solved or the feature implemented.

## Related Issue / Task
<!-- Link the issue or task that this PR resolves -->
Closes #<issue-number>

## Type of Change
- [ ] `feat`: New feature or user story implementation
- [ ] `fix`: Bug fix
- [ ] `chore`: Maintenance, dependencies, tooling, or configuration
- [ ] `docs`: Documentation updates (README, OpenAPI/Swagger, docstrings)
- [ ] `refactor`: Code refactoring without behavior changes
- [ ] `test`: Unit or integration tests added/updated
- [ ] `ci`: CI/CD pipeline or workflow changes

## Technical Checklist (Definition of Done)
- [ ] Code follows team conventions and all commit messages, branch names, and PR titles are written in **English**.
- [ ] Multi-tenant isolation verified: all client-facing queries are strictly scoped by `empresa_id`.
- [ ] Client serializers strictly omit internal management data (`responsable_id`, internal notes).
- [ ] Immutability enforced: no `UPDATE` or `DELETE` endpoints exposed for `TicketItem` audit records.
- [ ] Database migrations are checked and tested cleanly (`python manage.py makemigrations --check`).
- [ ] Unit & integration tests added/updated with `pytest` (test coverage >= 80%).
- [ ] Code formatted and linted (`ruff check .` / `ruff format .`).
- [ ] **STRICT NO SQUASH MERGE**: Merge method must be set to **"Create a merge commit"** (`--no-ff`).

## Reviewer Assignment (Code Owner)
- Assigned Code Owner: @<reviewer-username> (Reviewer must be one of `@AnorakTeam`, `@dannieltom`, `@sansviex`, `@tohond`)
